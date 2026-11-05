"""Orchestration : Janitor → conversion → Saucepan, pour tous les nouveaux bots."""

import re

from . import avatar, card, config, convert, janitor, saucepan, state
from .driver import BrowserSession, DriverError

# Numéro de saison dans un titre : « S9 », « S3.2 », « ALT S4 ». On ne retient
# que l'entier — « S3.2 » appartient à la saison 3.
SEASON = re.compile(r"\bS\s*(\d+)", re.I)


def season_excluded(name, settings):
    """Le titre relève-t-il d'une saison qu'on ne veut plus transférer ?

    Un titre sans numéro de saison n'est jamais écarté : la règle ne doit
    retirer que ce qu'elle reconnaît avec certitude.
    """
    name = name or ""
    for rule in settings.get("season_limits") or []:
        pattern = rule.get("pattern")
        floor = rule.get("from_season")
        if not pattern or floor is None:
            continue
        if not re.search(pattern, name, re.I):
            continue
        found = SEASON.search(name)
        if found and int(found.group(1)) >= int(floor):
            return True
    return False


def full_sync(settings, log, first_run_seed=False, dry_run=False, forced=None):
    """Un cycle, à condition qu'aucun autre ne tourne déjà (voir `_full_sync`)."""
    if not state.acquire_run_lock():
        log(state.log("Un autre cycle est déjà en cours — celui-ci est annulé."))
        return {"new": 0, "ok": 0, "failed": 0, "skipped": 0, "details": [],
                "dry_run": dry_run, "locked": True}
    try:
        return _full_sync(settings, log, first_run_seed, dry_run, forced)
    finally:
        state.release_run_lock()


def _full_sync(settings, log, first_run_seed=False, dry_run=False, forced=None):
    """`forced` : identifiants de bots à envoyer tels quels (voir sync_urls)."""
    """Une synchronisation complète.

    `first_run_seed` : enregistre les bots existants comme connus sans rien
    envoyer — à faire une fois, pour ne pas déverser tout l'historique du
    compte d'un coup.

    `dry_run` : va jusqu'au collage du JSON dans Saucepan puis s'arrête. Rien
    n'est restauré, enregistré ni publié.
    """
    list_url = settings.get("janitor_list_url")
    new_url = settings.get("saucepan_new_url")
    edit_template = settings.get("janitor_edit_template") or config.JANITOR_EDIT_URL

    if not list_url or not new_url:
        raise DriverError(
            "Configuration incomplète : renseignez l'URL de votre liste Janitor "
            "et celle de l'éditeur Saucepan (onglet Configuration)."
        )

    # Toute exécution est consignée, quelle que soit la façon dont elle a été
    # lancée. Auparavant seule l'interface écrivait au journal : les cycles
    # lancés en ligne de commande n'y laissaient aucune trace, et le fichier
    # donnait une image fausse de ce qui s'était réellement passé.
    display = log

    def say(message):
        # `display` est capturé avant la réaffectation : sans cela, `say`
        # s'appellerait lui-même indéfiniment.
        display(state.log(message))

    log = say

    results = {"new": 0, "ok": 0, "failed": 0, "skipped": 0, "details": [],
               "dry_run": dry_run}

    with BrowserSession(log, settings.get("browser_path")) as driver:
        characters = ([{"id": cid, "name": cid} for cid in forced] if forced
                      else janitor.list_characters(driver, list_url, log))

        if first_run_seed:
            state.seed_all([c["id"] for c in characters])
            log(f"{len(characters)} bot(s) enregistrés comme déjà connus. "
                "Seuls les prochains ajouts seront synchronisés.")
            results["seeded"] = len(characters)
            return results

        # Bots créés lors d'un cycle précédent mais restés à mi-chemin de la
        # publication : on les republie, sans jamais les recréer.
        if not dry_run and not forced:
            for cid, entry in state.awaiting_publish().items():
                label = entry.get("name") or cid
                level = entry.get("access_level") or "private"
                log(f"─── Reprise : {label} (déjà créé, publication inachevée)")
                try:
                    outcome = saucepan.publish_existing(
                        driver, entry["saucepan_url"], level, log)
                    state.mark_seen(cid, status="ok",
                                    saucepan_url=outcome.get("url") or entry["saucepan_url"])
                    results["ok"] += 1
                    results["details"].append({"id": cid, "name": label, "status": "ok"})
                    log(f"✅ {label} publié ({level}).")
                except Exception as exc:                           # noqa: BLE001
                    message = f"{type(exc).__name__}: {exc}"
                    state.mark_seen(cid, status="created", error=message)
                    results["failed"] += 1
                    results["details"].append({"id": cid, "name": label,
                                               "status": "failed", "error": message})
                    log(f"❌ {label} — publication toujours en échec : {message}")

        min_tokens = int(settings.get("min_tokens", 500) or 0)
        raw_limit = settings.get("daily_limit", 2)
        daily_limit = None if raw_limit in (None, "") else int(raw_limit)
        pause = float(settings.get("pause_between_bots", 20) or 0)

        if forced:
            # Envoi manuel : ni registre, ni filtres, ni plafond du jour.
            queue = characters
            results["new"] = len(queue)
            log(f"{len(queue)} bot(s) envoyé(s) à la demande."
                + (" [SIMULATION]" if dry_run else ""))
        else:
            pending = [c for c in characters if not state.is_seen(c["id"])]

            # Les sondages, annonces et cartes de mise à jour ne sont pas des
            # personnages : on les reconnaît à leur nombre de jetons dérisoire.
            # Le compte figure sur la carte, donc filtrer ici évite d'ouvrir des
            # centaines de fiches pour rien.
            if min_tokens:
                too_small = [c for c in pending
                             if c.get("tokens") is not None and c["tokens"] < min_tokens]
                pending = [c for c in pending
                           if c.get("tokens") is None or c["tokens"] >= min_tokens]
                if too_small:
                    log(f"{len(too_small)} élément(s) sous {min_tokens} jetons "
                        "ignoré(s) — sondages, annonces, brouillons.")
                    results["too_small"] = len(too_small)

            # Ne transférer que ce qui est déjà public sur Janitor. Un bot dont la
            # visibilité est inconnue est **conservé** : l'écarter reviendrait à
            # perdre silencieusement un bot légitime, et de toute façon la
            # conversion ne publie que sur un `is_public` explicitement vrai.
            if settings.get("public_only", True):
                private = [c for c in pending if c.get("is_public") is False]
                pending = [c for c in pending if c.get("is_public") is not False]
                if private:
                    log(f"{len(private)} bot(s) privé(s) sur Janitor ignoré(s).")
                    results["private"] = len(private)

            if not pending:
                log("Aucun nouveau bot à synchroniser.")
                return results

            excluded = [c for c in pending if season_excluded(c.get("name"), settings)]
            if excluded:
                pending = [c for c in pending if c not in excluded]
                log(f"{len(excluded)} bot(s) écarté(s) par les limites de saison : "
                    + ", ".join(c["name"][:40] for c in excluded[:4])
                    + (" …" if len(excluded) > 4 else ""))
                results["season_excluded"] = len(excluded)

            # Du plus récent au plus ancien : les bots récents sont ceux qu'on veut
            # voir arriver en premier sur Saucepan. Les fiches sans date passent en
            # dernier plutôt que d'être écartées.
            pending.sort(key=lambda c: c.get("created_at") or "", reverse=True)

            results["new"] = len(pending)

            # On n'envoie qu'un petit lot par exécution : mieux vaut étaler sur
            # plusieurs jours que risquer une limitation côté Saucepan. Les autres
            # restent en file et repartiront au prochain passage.
            # Un plafond de 0 signifie « aucun bot », pas « sans limite » : c'est
            # la lecture attendue de --limit 0, et l'inverse enverrait la file
            # entière d'un coup. Seule l'absence de valeur lève le plafond.
            queue = pending
            if daily_limit is not None and daily_limit >= 0:
                queue = pending[:daily_limit]
                results["queued"] = len(pending) - len(queue)

            if not queue:
                log(f"{len(pending)} bot(s) en attente, plafond du jour à "
                    f"{daily_limit} — rien à envoyer.")
                return results

            if results.get("queued"):
                log(f"{len(pending)} bot(s) en attente — {len(queue)} traité(s) "
                    f"aujourd'hui, {results['queued']} pour les jours suivants."
                    + (" [SIMULATION]" if dry_run else ""))
            else:
                log(f"{len(queue)} bot(s) à traiter."
                    + (" [SIMULATION]" if dry_run else ""))

        for index, char in enumerate(queue, 1):
            cid = char["id"]
            label = char.get("name") or cid
            created = {}
            log(f"─── [{index}/{len(queue)}] {label}" + (f" · {char['tokens']} jetons" if char.get("tokens") else ""))

            try:
                # Un bot envoyé à la demande peut ne pas vous appartenir.
                fetch = janitor.fetch_any_character if forced else janitor.fetch_character
                fiche = fetch(driver, cid, edit_template, log)
                label = fiche.get("name") or label

                # Saucepan exige une image de profil, et Janitor ne donne qu'un
                # nom de fichier sur son CDN : on rapatrie l'avatar pour le
                # redéposer dans le formulaire.
                image_path = None
                try:
                    image_path = avatar.download(fiche, log)
                except avatar.AvatarError as exc:
                    log(f"⚠ Avatar indisponible : {exc}")

                # L'identifiant d'image côté Saucepan n'existe qu'après le
                # dépôt ; on marque le champ pour que la validation locale ne
                # bloque pas un cas qui sera résolu dans le formulaire.
                placeholder = {"pending_upload": True} if image_path else None
                companion = convert.janitor_to_saucepan(fiche, image=placeholder)

                for tag in convert.dropped_tags(fiche):
                    log(f"⚠ Tag « {tag} » hors énumération Saucepan — retiré.")

                overflow = companion.get("_naosnatcher", {}).get("preview_overflow")
                if overflow:
                    log(f"⚠ Aperçu : le paragraphe d'accroche fait {overflow} "
                        f"caractères (max 140) — remplacé par le titre "
                        f"« {companion.get('short_description')} ».")
                    state.record_overflow(cid, companion.get("display_name") or label,
                                          overflow, companion.get("short_description"))

                problems = convert.validate(companion)
                if problems:
                    raise DriverError(
                        "JSON non conforme au schéma Saucepan :\n  - "
                        + "\n  - ".join(problems)
                    )

                export_path = convert.save_export(companion, cid)
                log(f"JSON écrit : {export_path}")

                # La carte de personnage, si demandée. Un échec ici ne doit
                # pas coûter la synchronisation elle-même.
                if settings.get("make_cards"):
                    try:
                        card.write_card(fiche, image_path, log)
                    except Exception as exc:                       # noqa: BLE001
                        log(f"⚠ Carte non créée : {exc}")

                level = companion.get("access_level", "private")
                title = companion.get("display_name") or companion.get("name")

                def on_created(url, cid=cid, title=title, level=level,
                               export_path=export_path):
                    # Inscrit tout de suite : si la publication échoue ensuite,
                    # le prochain cycle republiera cette companion au lieu
                    # d'en créer une seconde.
                    created["url"] = url
                    state.mark_seen(cid, name=title, status="created",
                                    access_level=level, saucepan_url=url,
                                    export=export_path)

                outcome = saucepan.restore_companion(
                    driver, new_url, convert.to_backup_string(companion),
                    level, log, dry_run=dry_run, image_path=image_path,
                    on_created=on_created,
                )

                if dry_run:
                    results["skipped"] += 1
                    results["details"].append({"id": cid, "name": label,
                                               "status": "simulé"})
                    continue

                state.mark_seen(
                    # Le titre, pas le nom court : « Sukuna » ne permettrait
                    # pas de reconnaître un bot parmi 76 homonymes.
                    cid, name=companion.get("display_name") or companion.get("name"),
                    status="ok",
                    access_level=companion.get("access_level"),
                    saucepan_url=outcome.get("url"), export=export_path,
                )
                results["ok"] += 1
                results["details"].append({"id": cid, "name": label, "status": "ok"})
                log(f"✅ {label} synchronisé ({companion.get('access_level')}).")

            except Exception as exc:                               # noqa: BLE001
                # Un bot qui échoue n'interrompt pas les suivants ; il reste
                # hors du registre et sera retenté à la prochaine exécution.
                message = f"{type(exc).__name__}: {exc}"
                if created:
                    # La companion existe déjà : on garde le statut « created »
                    # pour ne reprendre que la publication.
                    state.mark_seen(cid, status="created", error=message)
                elif not dry_run:
                    state.mark_seen(cid, name=label, status="failed", error=message)
                results["failed"] += 1
                results["details"].append({"id": cid, "name": label,
                                           "status": "failed", "error": message})
                log(f"❌ {label} — échec : {message}")
                if created:
                    log(f"   Déjà créé sur Saucepan ({created['url']}) — la "
                        "publication sera reprise au prochain cycle, sans "
                        "recréer la companion.")

            # Respiration entre deux bots, pour ne pas marteler les deux sites.
            if index < len(queue) and pause:
                driver.page.wait_for_timeout(int(pause * 1000))

    verb = "simulé" if dry_run else "terminé"
    log(f"Cycle {verb} : {results['ok']} réussi(s), {results['skipped']} simulé(s), "
        f"{results['failed']} échec(s).")
    return results


def make_cards(settings, log, char_ids=(), urls=()):
    """Crée les cartes de personnage de bots Janitor.

    `char_ids` : vos bots (déjà synchronisés, par exemple) ;
    `urls` : n'importe quelle page de bot Janitor, le vôtre ou non.
    Renvoie la liste des fichiers écrits.
    """
    edit_template = settings.get("janitor_edit_template") or config.JANITOR_EDIT_URL
    display = log

    def say(message):
        display(state.log(message))

    log = say
    jobs = [(cid, False) for cid in char_ids]
    jobs += [(card.char_id_from(u), True) for u in urls]
    if not jobs:
        return []

    if not state.acquire_run_lock():
        raise DriverError("Une synchronisation est en cours — réessayez ensuite.")
    written = []
    try:
        with BrowserSession(log, settings.get("browser_path")) as driver:
            for index, (cid, any_owner) in enumerate(jobs, 1):
                log(f"─── Carte [{index}/{len(jobs)}] {cid}")
                try:
                    if any_owner:
                        fiche = janitor.fetch_any_character(
                            driver, cid, edit_template, log)
                    else:
                        fiche = janitor.fetch_character(
                            driver, cid, edit_template, log)
                    written.append(card.write_card(fiche, None, log))
                except Exception as exc:                           # noqa: BLE001
                    log(f"❌ Carte {cid} — échec : {type(exc).__name__}: {exc}")
    finally:
        state.release_run_lock()
    log(f"{len(written)} carte(s) créée(s) dans {config.CARDS_DIR}")
    return written


SAUCEPAN_HOME = "https://saucepan.ai/"


def check_sessions(settings, log):
    """Êtes-vous connecté aux deux sites dans le navigateur piloté ?

    Renvoie {"janitor": bool, "saucepan": bool}.
    """
    result = {}
    with BrowserSession(log, settings.get("browser_path")) as driver:
        for site, url in (("janitor", settings.get("janitor_list_url")
                           or config.JANITOR_MY_CHARACTERS),
                          ("saucepan", SAUCEPAN_HOME)):
            try:
                driver.goto(url, expect_ok=False)
                driver.page.wait_for_timeout(4000)
                result[site] = not driver.is_logged_out()
            except Exception as exc:                               # noqa: BLE001
                log(f"{site} : {exc}")
                result[site] = False
    return result


def open_login_pages(settings, log):
    """Ouvre Janitor et Saucepan, chacun dans un onglet, pour s'y connecter."""
    with BrowserSession(log, settings.get("browser_path")) as driver:
        driver.page.goto(config.JANITOR_ORIGIN, wait_until="domcontentloaded")
        other = driver.page.context.new_page()
        other.goto(SAUCEPAN_HOME, wait_until="domcontentloaded")


def sync_urls(settings, log, urls, dry_run=False):
    """Envoie sur Saucepan les bots Janitor désignés par leur adresse.

    N'importe quel bot, sans les règles du cycle automatique : saisons
    écartées, bots privés, petits bots, plafond du jour, déjà synchronisé.
    """
    ids = list(dict.fromkeys(card.char_id_from(u) for u in urls))
    return full_sync(settings, log, dry_run=dry_run, forced=ids)
