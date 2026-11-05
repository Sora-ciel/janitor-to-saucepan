"""Persistance : bots déjà synchronisés, réglages, journal."""

import json
import os
import sys
import threading
import time
from datetime import datetime

from . import config

_lock = threading.Lock()


def _read(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ── Réglages ────────────────────────────────────────────────────────────────

DEFAULT_SETTINGS = {
    # URLs capturées pendant la configuration guidée. On ne devine rien :
    # l'utilisateur navigue jusqu'à la bonne page et clique sur "Capturer".
    "janitor_list_url": "",
    "saucepan_new_url": "",
    # Gabarit de l'URL d'édition d'un bot. {char_id} est remplacé à l'exécution.
    # Modifiable si Janitor change de structure d'URL.
    "janitor_edit_template": config.JANITOR_EDIT_URL,
    "daily_hour": config.DAILY_HOUR,
    "daily_minute": config.DAILY_MINUTE,
    "enabled": True,
    "last_run": "",

    # Un bot en dessous de ce nombre de jetons n'est pas un personnage : les
    # sondages, annonces et cartes de mise à jour n'en comptent qu'une poignée.
    "min_tokens": 500,

    # Ne transférer que les bots déjà publics sur Janitor.
    "public_only": True,

    # Séries dont on ne veut pas les saisons récentes. Un bot est écarté si son
    # titre correspond au motif **et** porte un numéro de saison supérieur ou
    # égal à `from_season`. Les titres sans numéro sont conservés : mieux vaut
    # transférer un bot de trop que d'en perdre un par une lecture hasardeuse.
    "season_limits": [
        {"pattern": r"neon red light|\bNRL\b", "from_season": 6},
    ],

    # Nombre de bots envoyés par exécution. Volontairement bas : publier en
    # rafale sur Saucepan risquerait d'y déclencher une limitation.
    "daily_limit": 2,

    # Pause entre deux bots d'une même exécution, en secondes.
    "pause_between_bots": 20,

    # Créer aussi une carte de personnage (PNG) pour chaque bot synchronisé.
    "make_cards": False,

    # L'assistant de configuration a-t-il été mené à son terme ?
    "setup_done": False,
}


def clean_url(url):
    """Nettoie une URL saisie à la main.

    Attrape notamment le collage en double (« https://a/bhttps://a/b »), qui
    donne sinon une navigation vers une adresse inexistante sans explication.
    """
    if not isinstance(url, str):
        return url
    url = url.strip().strip('"').strip("'")
    for scheme in ("https://", "http://"):
        second = url.find(scheme, len(scheme))
        if second > 0:
            first, rest = url[:second], url[second:]
            # On ne coupe que si les deux moitiés sont identiques : une URL
            # qui contient légitimement une autre URL est laissée intacte.
            if first == rest:
                return first
    return url


def load_settings():
    s = dict(DEFAULT_SETTINGS)
    s.update(_read(config.SETTINGS_FILE, {}))

    # Migration unique (0.3.0) : l'adresse de la liste Janitor est désormais
    # verrouillée ; on remet la bonne à ceux qui l'avaient modifiée. Une
    # installation pas encore configurée n'est pas touchée : l'assistant s'en
    # charge.
    if s.get("janitor_list_url") and not s.get("list_url_reset_0_3"):
        s["janitor_list_url"] = config.JANITOR_MY_CHARACTERS
        s["list_url_reset_0_3"] = True
        save_settings(s)

    # Migration : remplacer un gabarit d'édition devenu faux.
    if s.get("janitor_edit_template") in config.JANITOR_EDIT_URL_OBSOLETE:
        s["janitor_edit_template"] = config.JANITOR_EDIT_URL
        save_settings(s)

    for key in ("janitor_list_url", "saucepan_new_url"):
        cleaned = clean_url(s.get(key))
        if cleaned != s.get(key):
            s[key] = cleaned
            save_settings(s)

    return s


def save_settings(settings):
    with _lock:
        _write(config.SETTINGS_FILE, settings)


def set_setting(key, value):
    s = load_settings()
    s[key] = value
    save_settings(s)
    return s


# ── Bots déjà traités ───────────────────────────────────────────────────────
#
# Structure : { "<janitor_char_id>": {
#     "name": ..., "synced_at": ISO8601, "saucepan_url": ...,
#     "access_level": "public"|"private", "status": "ok"|"failed",
#     "error": "..." } }


def load_seen():
    return _read(config.SEEN_FILE, {})


def is_seen(char_id):
    """Un bot est 'vu' dès qu'il existe sur Saucepan.

    Un échec avant la création reste dans la file d'attente et sera retenté le
    lendemain. Un bot « created » — créé, mais dont la publication a échoué —
    ne doit en revanche **jamais** être recréé : c'est ce qui produisait des
    doublons. Sa publication est reprise à part (voir `awaiting_publish`).
    """
    entry = load_seen().get(str(char_id))
    return bool(entry) and entry.get("status") in ("ok", "created")


def awaiting_publish():
    """Bots créés sur Saucepan dont la publication reste à faire."""
    return {cid: e for cid, e in load_seen().items()
            if e.get("status") == "created" and e.get("saucepan_url")}


def mark_seen(char_id, **fields):
    with _lock:
        seen = _read(config.SEEN_FILE, {})
        entry = seen.get(str(char_id), {})
        entry.update(fields)
        # Une réussite doit effacer l'échec précédent : sans cela, un bot
        # rattrapé au cycle suivant garderait indéfiniment un message d'erreur
        # trompeur dans le registre.
        if entry.get("status") == "ok":
            entry.pop("error", None)
        entry.setdefault("first_seen", datetime.now().isoformat(timespec="seconds"))
        entry["synced_at"] = datetime.now().isoformat(timespec="seconds")
        seen[str(char_id)] = entry
        _write(config.SEEN_FILE, seen)


def forget(char_id):
    """Retire un bot du registre pour forcer une resynchronisation."""
    with _lock:
        seen = _read(config.SEEN_FILE, {})
        seen.pop(str(char_id), None)
        _write(config.SEEN_FILE, seen)


def seed_all(char_ids):
    """Marque une liste de bots comme déjà connus, sans les synchroniser.

    Utilisé au premier lancement : on ne veut pas que l'app tente d'envoyer
    d'un coup les 40 bots déjà présents sur le compte.
    """
    with _lock:
        seen = _read(config.SEEN_FILE, {})
        now = datetime.now().isoformat(timespec="seconds")
        for cid in char_ids:
            seen.setdefault(str(cid), {
                "status": "ok",
                "first_seen": now,
                "synced_at": now,
                "note": "pré-existant, ignoré au premier lancement",
            })
        _write(config.SEEN_FILE, seen)


# ── Reprise d'une installation précédente ───────────────────────────────────

IMPORTABLE = ("seen_bots.json", "settings.json", "housestyle.json",
              "preview_overflows.json")


def import_data(folder):
    """Reprend le registre et les réglages d'une autre installation.

    Accepte le dossier du projet comme son sous-dossier `data`. Sans cette
    reprise, une nouvelle installation croirait n'avoir jamais rien envoyé et
    renverrait tout l'historique du compte. Renvoie les fichiers copiés.
    """
    import shutil

    source = folder
    if not os.path.isfile(os.path.join(source, "seen_bots.json")):
        source = os.path.join(folder, "data")
    if not os.path.isfile(os.path.join(source, "seen_bots.json")):
        raise FileNotFoundError(
            "Aucun seen_bots.json dans ce dossier ni dans son sous-dossier data.")
    if os.path.abspath(source) == os.path.abspath(config.DATA_DIR):
        return []

    copied = []
    with _lock:
        for name in IMPORTABLE:
            src = os.path.join(source, name)
            if os.path.isfile(src):
                shutil.copyfile(src, os.path.join(config.DATA_DIR, name))
                copied.append(name)
    # Un navigateur réglé sur l'autre installation n'a rien à faire ici.
    settings = _read(config.SETTINGS_FILE, {})
    settings.pop("browser_path", None)
    _write(config.SETTINGS_FILE, settings)
    return copied


# ── Verrou d'exécution ──────────────────────────────────────────────────────
#
# La fenêtre et le minuteur système peuvent partir à la même minute. Deux cycles
# simultanés traiteraient les mêmes bots et créeraient des doublons : un seul
# à la fois. Le verrou est un fichier, pour valoir entre deux processus.

LOCK_FILE = os.path.join(config.DATA_DIR, "sync.lock")
LOCK_STALE = 3600   # secondes — au-delà, un verrou est celui d'un cycle mort


def _lock_owner_alive():
    """Le processus inscrit dans le verrou tourne-t-il encore ?

    Le verrou note son PID : s'en servir evite d'attendre l'heure entiere de
    LOCK_STALE apres un cycle tue ou plante. Sans cela, un plantage a 7 h 50
    ferait sauter la synchronisation de 8 h.
    """
    try:
        with open(LOCK_FILE, "r", encoding="utf-8") as f:
            pid = int(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return False          # verrou illisible : on le considere abandonne
    if pid == os.getpid():
        return True

    if sys.platform == "win32":
        # `os.kill(pid, 0)` ne convient pas ici : sous Windows il leve une
        # OSError generique pour un PID disparu, indiscernable d'un refus
        # d'acces. Un processus mort passait donc pour vivant.
        import ctypes

        QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False                      # introuvable : cycle mort
        try:
            code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return True
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)       # signal 0 : ne fait rien, teste l'existence
    except ProcessLookupError:
        return False
    except PermissionError:
        return True           # vivant, mais appartenant a quelqu'un d'autre
    except OSError:
        return True           # dans le doute, on respecte le verrou
    return True


def acquire_run_lock():
    """Prend le verrou ; False si un autre cycle tourne déjà."""
    try:
        too_old = time.time() - os.path.getmtime(LOCK_FILE) > LOCK_STALE
        if too_old or not _lock_owner_alive():
            os.remove(LOCK_FILE)
    except OSError:
        pass
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w") as f:
        f.write(f"{os.getpid()} {datetime.now().isoformat(timespec='seconds')}\n")
    return True


def release_run_lock():
    try:
        os.remove(LOCK_FILE)
    except OSError:
        pass


# ── Journal ─────────────────────────────────────────────────────────────────

# ── Aperçus trop longs ──────────────────────────────────────────────────────
#
# Quand le paragraphe d'accroche dépasse les 140 caractères de Saucepan, on
# retombe sur le titre — correct, mais moins parlant. On garde la trace du cas
# pour pouvoir prévenir l'auteur : c'est à lui d'écrire un vrai résumé.

OVERFLOW_FILE = os.path.join(config.DATA_DIR, "preview_overflows.json")


def record_overflow(char_id, name, length, used, saucepan_url=""):
    with _lock:
        entries = _read(OVERFLOW_FILE, [])
        entries = [e for e in entries if e.get("id") != str(char_id)]
        entries.append({
            "id": str(char_id),
            "name": name,
            "paragraph_length": length,
            "limit": 140,
            "used_instead": used,
            "saucepan_url": saucepan_url,
            "at": datetime.now().isoformat(timespec="seconds"),
        })
        _write(OVERFLOW_FILE, entries)


def load_overflows(pending_only=True):
    entries = _read(OVERFLOW_FILE, [])
    return [e for e in entries if not e.get("notified")] if pending_only else entries


def mark_overflows_notified(ids):
    with _lock:
        entries = _read(OVERFLOW_FILE, [])
        wanted = {str(i) for i in ids}
        stamp = datetime.now().isoformat(timespec="seconds")
        for entry in entries:
            if entry.get("id") in wanted:
                entry["notified"] = stamp
        _write(OVERFLOW_FILE, entries)


def log(message):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
    with _lock:
        with open(config.LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    return line


def tail_log(lines=300):
    try:
        with open(config.LOG_FILE, "r", encoding="utf-8") as f:
            return f.read().splitlines()[-lines:]
    except OSError:
        return []
