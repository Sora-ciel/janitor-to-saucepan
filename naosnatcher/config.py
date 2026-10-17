"""Chemins et constantes partagés par toute l'application."""

import os
import sys

# -- Ou vivent les donnees --------------------------------------------------
#
# Trois facons de tourner :
#   - depuis les sources : tout vit dans le dossier du projet ;
#   - installe (.exe) : le programme est en lecture seule et les donnees vont
#     par defaut dans %LOCALAPPDATA%\Naosnatcher ;
#   - emplacement choisi : un dossier indique par l'utilisateur, par exemple
#     sur une partition partagee entre Windows et Linux, pour que les deux
#     systemes travaillent sur le meme registre.
#
# L'emplacement est resolu dans cet ordre :
#   1. la variable d'environnement NAOSNATCHER_DATA ;
#   2. le fichier-repere, propre a chaque systeme ;
#   3. l'emplacement par defaut.
#
# Le repere ne peut pas vivre dans le dossier de donnees -- il sert justement a
# le trouver. Il est donc range a un endroit fixe, propre au systeme.
FROZEN = getattr(sys, "frozen", False)
PLATFORM = "win32" if sys.platform == "win32" else (
    "macos" if sys.platform == "darwin" else "linux")

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)) \
    if FROZEN else PROJECT_DIR


def local_base():
    """Dossier propre a ce systeme, jamais partage."""
    if sys.platform == "win32":
        return os.path.join(os.environ.get("LOCALAPPDATA")
                            or os.path.expanduser("~"), "Naosnatcher")
    return os.path.expanduser("~/.local/share/naosnatcher")


def default_root():
    """Emplacement des donnees quand rien n'a ete choisi."""
    return local_base() if FROZEN else PROJECT_DIR


def pointer_file():
    """Fichier indiquant ou sont les donnees. Propre a chaque systeme."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "Naosnatcher", "data_location.txt")
    return os.path.expanduser("~/.config/naosnatcher/data_location")


def read_pointer():
    try:
        with open(pointer_file(), "r", encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def write_pointer(path):
    """Enregistre l'emplacement choisi, ou l'efface si `path` est vide.

    Le changement ne prend effet qu'au redemarrage : les chemins sont calcules
    une seule fois, a l'import, et une bascule a chaud laisserait des modules
    pointant vers l'ancien dossier.
    """
    target = pointer_file()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if not path:
        if os.path.exists(target):
            os.remove(target)
        return None
    path = os.path.abspath(os.path.expanduser(path))
    os.makedirs(path, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(path)
    return path


def resolve_root():
    """(emplacement, origine) -- origine parmi env, pointer, default."""
    from_env = (os.environ.get("NAOSNATCHER_DATA") or "").strip()
    if from_env:
        return os.path.abspath(os.path.expanduser(from_env)), "env"
    pointed = read_pointer()
    if pointed:
        return pointed, "pointer"
    return default_root(), "default"


ROOT, ROOT_SOURCE = resolve_root()
BUNDLED_DATA = os.path.join(BUNDLE, "data")

# Donnees partageables entre systemes : registre, reglages, journal, exports.
DATA_DIR = os.path.join(ROOT, "data")
SEEN_FILE = os.path.join(DATA_DIR, "seen_bots.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
LOG_FILE = os.path.join(DATA_DIR, "sync.log")
EXPORT_DIR = os.path.join(ROOT, "exports")
CARDS_DIR = os.path.join(ROOT, "cards")

# Profil du navigateur : cookies et localStorage des deux sites.
#
# **Jamais partage entre systemes**, meme quand le reste l'est : un profil
# Chromium pese plusieurs centaines de Mo et contient des chemins absolus, des
# verrous et des binaires propres a la plateforme. Chaque systeme a donc son
# sous-dossier, ce qui permet de partager le dossier parent sans rien casser.
BROWSER_ROOT = os.path.join(ROOT, "browser_state")
BROWSER_STATE = os.path.join(BROWSER_ROOT, PLATFORM)

# Fournis avec l'application, en lecture seule.
TAGS_FILE = os.path.join(BUNDLED_DATA, "saucepan_tags.json")
ICON_FILE = os.path.join(BUNDLE, "packaging", "naosnatcher.png")

for _d in (BROWSER_STATE, DATA_DIR, EXPORT_DIR, CARDS_DIR):
    os.makedirs(_d, exist_ok=True)

# Reprise de l'ancienne disposition : le profil vivait directement dans
# browser_state/. On le deplace dans le sous-dossier du systeme courant pour ne
# pas perdre les sessions ouvertes -- un renommage, pas une copie : le profil
# approche les 800 Mo.
_legacy = os.path.join(BROWSER_ROOT, "cdp_profile")
_current = os.path.join(BROWSER_STATE, "cdp_profile")
if os.path.isdir(_legacy) and not os.path.exists(_current):
    try:
        os.rename(_legacy, _current)
    except OSError:
        pass

# Premiere execution d'une version installee : la mise en forme maison part de
# celle livree avec l'application, plutot que de valeurs codees en dur.
_src = os.path.join(BUNDLED_DATA, "housestyle.json")
_dst = os.path.join(DATA_DIR, "housestyle.json")
if os.path.isfile(_src) and not os.path.exists(_dst):
    import shutil
    shutil.copyfile(_src, _dst)

# ── Janitor AI ──────────────────────────────────────────────────────────────
# Routes relevées dans la table de routage du site elle-même :
#   character:       /characters/:characterId
#   edit_character:  /edit_character/:characterId
#   my_characters:   /my_characters
JANITOR_ORIGIN = "https://janitorai.com"
JANITOR_MY_CHARACTERS = f"{JANITOR_ORIGIN}/my_characters"
JANITOR_EDIT_URL = f"{JANITOR_ORIGIN}/edit_character/{{char_id}}"
JANITOR_VIEW_URL = f"{JANITOR_ORIGIN}/characters/{{char_id}}"

# Anciens gabarits erronés, remplacés automatiquement dans les réglages
# existants (voir state.load_settings).
JANITOR_EDIT_URL_OBSOLETE = {
    f"{JANITOR_ORIGIN}/characters/{{char_id}}/edit",
}

# ── Saucepan AI ─────────────────────────────────────────────────────────────
SAUCEPAN_ORIGIN = "https://saucepan.ai"
SAUCEPAN_API = "https://api.saucepan.ai"
# Page d'édition d'une nouvelle companion (c'est là qu'on colle le backup JSON).
SAUCEPAN_NEW_COMPANION = f"{SAUCEPAN_ORIGIN}/companions/new"

# ── Planification ───────────────────────────────────────────────────────────
DAILY_HOUR = 8
DAILY_MINUTE = 0

# User-agent : on se fait passer pour un Chrome desktop standard, sinon
# certains sites servent une version dégradée à QtWebEngine.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
