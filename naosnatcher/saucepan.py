"""Envoi d'une companion sur Saucepan AI.

L'éditeur est découpé en plusieurs pages, chacune avec sa propre URL :

    /editor/new/settings   Backup/Restore Companion — c'est là qu'on colle
    /editor/new/profile    avatar (#profile-image) et bannière
    /editor/new/publish    visibilité + enregistrement

Le bouton d'enregistrement est en bas à gauche et reste affiché sur toutes les
pages ; la companion doit être complète, et passée en public, avant de le
cliquer.

Point d'attention : tant que la companion n'est pas enregistrée, elle n'existe
que côté navigateur (« This companion is not saved yet »). Passer d'une page à
l'autre par un rechargement complet risquerait de perdre ce brouillon, aussi
on privilégie la navigation interne à l'application.
"""

import re
from urllib.parse import urlsplit, urlunsplit

from . import avatar as avatar_mod
from . import convert
from .driver import DriverError

# Le bouton d'enregistrement, relevé sur la page de publication : « Create »
# pour une nouvelle companion, en bas à gauche, sur toute la largeur. Il reste
# **désactivé** tant que la companion n'est pas valide. « Save » / « Update »
# sont conservés pour le cas d'une companion déjà existante.
SAVE_LABELS = ["Create", "Save", "Update", "Save Companion", "Save Changes"]

# La visibilité est un jeu de trois boutons dont les libellés correspondent
# exactement à l'énumération `access_level` de Saucepan.
VISIBILITY_LABELS = {
    "private": "Private",
    "unlisted": "Unlisted",
    "public": "Public",
}


def editor_page(configured_url, page_name):
    """Dérive l'URL d'une page de l'éditeur à partir de celle configurée.

    `https://saucepan.ai/editor/new/settings` + "publish"
        → `https://saucepan.ai/editor/new/publish`
    """
    parts = urlsplit(configured_url)
    path = re.sub(r"/(settings|publish|[^/]*)$", f"/{page_name}", parts.path) \
        if parts.path.rstrip("/") else f"/editor/new/{page_name}"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def open_editor(driver, url, log):
    log(f"Ouverture de l'éditeur Saucepan : {url}")
    driver.goto(url)
    if driver.is_logged_out():
        raise DriverError(
            "Session Saucepan expirée. Connectez-vous dans la fenêtre du "
            "navigateur, puis relancez la synchronisation."
        )
    wait_ready(driver, "settings", log)


# Élément qui prouve qu'une page de l'éditeur a fini de se monter. Sans cette
# attente, on interroge un DOM encore vide et on conclut à tort que le champ
# ou le bouton n'existe pas.
PAGE_READY = {
    "profile": "document.querySelector('#profile-image')",
    "settings": "!!window.__naos && (window.__naos.backupTextarea() "
                "|| window.__naos.buttonByText('Restore Companion'))",
    "publish": "!!window.__naos && window.__naos.buttonByText('Public')",
}


def wait_ready(driver, page_name, log, timeout=30_000):
    """Attend que la page nommée soit réellement montée."""
    condition = PAGE_READY.get(page_name)
    if not condition:
        driver.page.wait_for_timeout(1500)
        return
    try:
        driver.wait_for(condition, timeout=timeout)
    except Exception:                                              # noqa: BLE001
        log(f"⚠ La page « {page_name} » n'a pas présenté son contenu attendu.")


# La barre latérale de l'éditeur : une colonne de 60 px, collée à gauche, faite
# de tuiles d'environ 60×52 contenant chacune une icône. Ce sont des <div>, pas
# des liens — la navigation est donc gérée par React, et c'est précisément ce
# qui préserve le brouillon en cours. Passer par l'URL, à l'inverse, recharge
# l'application et emporte la companion non enregistrée (avatar compris).
#
# On les repère par leur géométrie : les classes (`sc-cnLhvP`…) sont générées
# et changent à chaque déploiement.
JS_RAIL_ITEMS = """
() => {
  const items = [];
  for (const el of document.querySelectorAll('div')) {
    const r = el.getBoundingClientRect();
    if (r.left > 4 || r.width < 40 || r.width > 90) continue;
    if (r.height < 38 || r.height > 72) continue;
    if (!el.querySelector('svg')) continue;
    if (el.querySelectorAll('svg').length > 2) continue;
    items.push(el);
  }
  items.forEach((el, i) => el.setAttribute('data-naos-rail', String(i)));
  return items.length;
}
"""


def rail_items(driver):
    """Numérote les tuiles de la barre latérale et renvoie leur nombre."""
    return driver.eval_js(JS_RAIL_ITEMS) or 0


def go_to_editor_page(driver, url, page_name, log):
    """Rejoint une page de l'éditeur sans perdre le brouillon en cours.

    Les tuiles n'ont ni libellé ni URL : on ne peut donc pas deviner laquelle
    mène où. On clique, on regarde l'adresse obtenue, et on retient la
    correspondance pour la suite de la session — l'ordre des icônes n'a pas à
    être supposé, et un réagencement du site se corrige tout seul.
    """
    if driver.url().rstrip("/").endswith("/" + page_name):
        wait_ready(driver, page_name, log)
        return True

    cache = driver.rail_cache
    count = rail_items(driver)

    if count:
        # D'abord la tuile déjà identifiée, puis les autres.
        order = ([cache[page_name]] if page_name in cache else []) + \
                [i for i in range(count) if cache.get(page_name) != i]

        for index in order:
            try:
                driver.page.click(f'[data-naos-rail="{index}"]', timeout=5_000)
            except Exception:                                      # noqa: BLE001
                # Juste après un enregistrement, Saucepan remonte la barre :
                # la tuile visée disparaît sous le curseur (« element was
                # detached »). On renumérote et on passe à la suivante.
                driver.page.wait_for_timeout(1000)
                rail_items(driver)
                continue
            driver.page.wait_for_timeout(1100)
            driver.install_helpers()
            path = driver.eval_js("() => location.pathname")
            reached = path.rstrip("/").rsplit("/", 1)[-1]
            cache[reached] = index
            if reached == page_name:
                wait_ready(driver, page_name, log)
                log(f"Page « {page_name} » rejointe par la barre latérale.")
                return True
            rail_items(driver)   # le DOM a changé : on renumérote

    # Dernier recours. Le brouillon n'y survivra probablement pas.
    log(f"⚠ « {page_name} » introuvable dans la barre latérale — navigation "
        "par URL. Le brouillon non enregistré sera perdu.")
    driver.goto(editor_page(url, page_name))
    wait_ready(driver, page_name, log)
    return False


def open_restore_panel(driver, log):
    """Déplie la section de restauration.

    À l'ouverture de la page, le panneau est replié : ni zone de collage, ni
    bouton « Restore Data ». Il faut cliquer « Restore Companion » pour le
    faire apparaître.
    """
    if driver.eval_js("() => !!window.__naos.backupTextarea()"):
        return False

    state = driver.button_state("Restore Companion")
    if not state.get("present"):
        raise DriverError(
            "Ni zone de collage ni bouton « Restore Companion » sur cette "
            "page. L'URL configurée pointe-t-elle bien vers l'onglet des "
            "réglages de l'éditeur ?"
        )

    driver.click_label("Restore Companion")
    driver.page.wait_for_timeout(1200)
    log("Panneau de restauration déplié.")
    return True


def reset_draft(driver, log):
    """Demande la remise à zéro du brouillon de `/editor/new`.

    ⚠️ « Reset Changes » ne vide pas la fiche : il revient au dernier état
    enregistré, et pour une companion jamais enregistrée il ne fait
    pratiquement rien — vérifié, le brouillon garde le bot précédent.

    Ce n'est donc **pas** ce qui protège d'une contamination entre deux bots.
    La vraie garantie est ailleurs : le JSON collé contient les 34 clés du
    gabarit, et `merge_onto_base()` les superpose toutes au brouillon. Chaque
    champ est donc réécrit, quels que soient les restes. Seule `image` est
    reprise du brouillon — et c'est voulu, puisqu'on vient d'y déposer
    l'avatar du bot en cours.

    On tente quand même la remise à zéro : c'est gratuit, et cela réduit ce
    qui traîne dans les champs hors gabarit (recadrages, bannière).
    """
    for label in ("Reset Changes", "Reset Draft Changes", "Reset"):
        state = driver.button_state(label)
        if not state.get("present") or state.get("disabled"):
            continue
        driver.click_label(label)
        driver.page.wait_for_timeout(1200)

        # Une confirmation peut s'interposer.
        for confirm in ("Reset", "Confirm", "Yes", "OK"):
            st = driver.button_state(confirm)
            if st.get("present") and not st.get("disabled"):
                driver.click_label(confirm)
                driver.page.wait_for_timeout(1000)
                break

        log("Remise à zéro du brouillon demandée.")
        return True
    return False


def read_own_backup(driver, log):
    """Demande à Saucepan son propre backup et le renvoie déjà analysé.

    C'est notre gabarit de départ : il porte l'identifiant de l'image qu'on
    vient de déposer, ainsi que tous les champs qu'on ne sait pas traduire.
    """
    import json as _json

    open_restore_panel(driver, log)
    driver.click_label("Backup Companion")
    driver.page.wait_for_timeout(2000)

    raw = driver.eval_js(
        "() => { const t = window.__naos.backupTextarea(); return t ? t.value : null; }")
    if not raw:
        raise DriverError("« Backup Companion » n'a rien produit.")

    # La zone est un basculeur : « Backup Companion » l'affiche en lecture
    # seule. Il faut repasser en mode restauration pour pouvoir y écrire.
    driver.click_label("Restore Companion")
    driver.page.wait_for_timeout(1200)
    editable = driver.eval_js(
        "() => { const t = window.__naos.backupTextarea();"
        " return !!t && !t.readOnly && !t.disabled; }")
    if not editable:
        raise DriverError(
            "La zone de collage est restée en lecture seule après « Restore "
            "Companion »."
        )

    try:
        return _json.loads(raw)
    except ValueError as exc:
        raise DriverError(f"Backup Saucepan illisible : {exc}") from exc


def paste_backup(driver, backup_json_text, log):
    """Colle le backup et attend que « Restore Data » s'active."""
    open_restore_panel(driver, log)

    try:
        driver.wait_for("!!window.__naos && !!window.__naos.backupTextarea()",
                        timeout=20_000)
    except Exception as exc:                                       # noqa: BLE001
        raise DriverError(
            "Zone « Paste Companion Backup » introuvable après ouverture du "
            "panneau de restauration."
        ) from exc

    written = driver.fill_backup(backup_json_text)
    log(f"Backup collé ({written} caractères).")

    # « Restore Data » ne s'active qu'une fois React averti du changement.
    try:
        driver.wait_for(
            "(() => { const b = window.__naos.buttonByText('Restore Data');"
            " return b && !b.disabled; })()",
            timeout=15_000,
        )
    except Exception as exc:                                       # noqa: BLE001
        # Le site refuse en silence : le bouton reste grisé. Ses raisons sont
        # affichées sous « Validation errors » — sans elles, un échec ici
        # n'apprend rien et oblige à tout reproduire à la main.
        errors = driver.validation_errors()
        raise DriverError(
            "« Restore Data » est resté désactivé — Saucepan refuse le JSON."
            + (f"\n{errors}" if errors
               else " Aucun détail affiché ; vérifiez que la zone de collage "
                    "est bien celle de la section Backup/Restore.")
        ) from exc
    return written


def set_visibility(driver, level, log):
    """Règle la visibilité sur « Private », « Unlisted » ou « Public ».

    On reproduit exactement le niveau du bot côté Janitor, plutôt que de se
    contenter d'un basculement public/privé.
    """
    label = VISIBILITY_LABELS.get(level)
    if not label:
        # Un niveau inconnu ne doit jamais se transformer en publication.
        log(f"⚠ Niveau « {level} » inconnu — repli sur Private.")
        label = VISIBILITY_LABELS["private"]

    state = driver.button_state(label)
    if not state.get("present"):
        raise DriverError(
            f"Bouton de visibilité « {label} » introuvable sur la page de "
            "publication."
        )

    driver.click_label(label)
    driver.page.wait_for_timeout(1200)
    log(f"Visibilité réglée sur « {label} ».")
    return label


def _click_and_confirm_save(driver, label, timeout=12_000):
    """Clique le bouton et vérifie qu'un enregistrement a bien eu lieu.

    Preuve retenue : un appel d'écriture vers l'API de Saucepan, ou le passage
    de l'adresse `/editor/new/…` à `/editor/<identifiant>/…`. Le bouton peut
    en effet rester actif et ne rien faire (cas de la création directe en
    public) : sans cette vérification, on annoncerait un succès imaginaire.
    """
    calls = []

    def on_request(request):
        if request.method in ("POST", "PUT", "PATCH") and "saucepan" in request.url \
                and "sentry" not in request.url:
            calls.append(request.url)

    before = driver.url()
    driver.page.on("request", on_request)
    try:
        driver.click_label(label)
        waited = 0
        while waited < timeout:
            driver.page.wait_for_timeout(500)
            waited += 500
            if calls or driver.url() != before:
                driver.page.wait_for_timeout(2500)
                return True
    finally:
        driver.page.remove_listener("request", on_request)
    return bool(calls) or driver.url() != before


def save(driver, log):
    """Clique le bouton d'enregistrement, en bas à gauche.

    Ce bouton (« Create » pour une nouvelle companion) reste désactivé tant
    que la fiche n'est pas valide : un bouton présent mais grisé signifie
    qu'il manque quelque chose, et le dire explicitement évite de chercher
    un bouton absent qui, lui, est bien là.
    """
    for label in SAVE_LABELS:
        state = driver.button_state(label)
        if not state.get("present"):
            continue
        if state.get("disabled"):
            errors = driver.validation_errors()
            raise DriverError(
                f"Le bouton « {label} » est désactivé : la companion est "
                "incomplète pour Saucepan."
                + (f"\n{errors}" if errors else
                   " Aucun détail affiché par le site.")
            )
        before = driver.url()
        saved = _click_and_confirm_save(driver, label)
        log(f"Enregistré via « {label} ».")

        errors = driver.validation_errors()
        if errors:
            raise DriverError(f"Refus à l'enregistrement —\n{errors}")

        if not saved:
            # Le bouton peut ne rien déclencher du tout — c'est ce que fait
            # Saucepan quand on tente de créer directement en public. Sans ce
            # contrôle, l'app annoncerait un succès imaginaire.
            raise DriverError(
                f"« {label} » n'a produit aucun enregistrement (ni requête, ni "
                f"changement d'adresse ; toujours sur {before}). La companion "
                "n'a pas été sauvegardée."
            )
        return label

    raise DriverError(
        f"Aucun bouton d'enregistrement parmi : {', '.join(SAVE_LABELS)}."
    )


def publish_and_verify(driver, wanted, log):
    """Confirme le changement de visibilité sur une companion enregistrée.

    Sur une companion déjà créée, changer la visibilité est **enregistré
    automatiquement** : le bouton « Save » redevient alors grisé, ce qui est
    normal et non un échec. On ne se fie donc pas au bouton mais au résultat —
    on relit la fiche depuis le serveur.
    """
    state = driver.button_state("Save")
    if state.get("present") and not state.get("disabled"):
        _click_and_confirm_save(driver, "Save")
        log("Modification enregistrée via « Save ».")
    else:
        log("Rien à enregistrer — la visibilité est sauvegardée automatiquement.")

    driver.page.wait_for_timeout(2500)

    # Vérification sur rechargement : ce qu'on relit vient du serveur.
    current = driver.url().split("/publish")[0]
    driver.goto(current + "/settings")
    wait_ready(driver, "settings", log)
    got = read_own_backup(driver, log).get("access_level")

    if got != wanted:
        raise DriverError(
            f"Visibilité non appliquée : demandée « {wanted} », "
            f"enregistrée « {got} »."
        )
    log(f"Visibilité confirmée sur le serveur : {got}.")
    return got


def editor_base(url):
    """`https://saucepan.ai/editor/<id>/publish` → `https://saucepan.ai/editor/<id>`."""
    parts = urlsplit(url)
    path = re.sub(r"/(settings|publish|profile)/?$", "", parts.path.rstrip("/"))
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def publish_existing(driver, editor_url, access_level, log):
    """Republie une companion déjà créée, sans rien recréer.

    Sert à reprendre un cycle interrompu entre « Create » et la publication :
    la companion existe déjà côté Saucepan, il ne reste qu'à régler sa
    visibilité.
    """
    url = editor_base(editor_url) + "/publish"
    log(f"Reprise de la publication : {url}")
    driver.goto(url)
    if driver.is_logged_out():
        raise DriverError(
            "Session Saucepan expirée. Connectez-vous dans la fenêtre du "
            "navigateur, puis relancez la synchronisation."
        )
    wait_ready(driver, "publish", log)
    set_visibility(driver, access_level, log)
    publish_and_verify(driver, access_level, log)
    return {"url": driver.url()}


def restore_companion(driver, settings_url, backup_json_text, access_level, log,
                      dry_run=False, image_path=None, on_created=None):
    """Parcours complet : collage, restauration, avatar, visibilité, save.

    `access_level` : « private », « unlisted » ou « public » — recopié depuis
    Janitor, pour que la companion Saucepan ait la même visibilité.

    `dry_run` : s'arrête juste après le collage. Rien n'est restauré,
    enregistré ni publié.

    `on_created(url)` : appelé dès que la companion existe sur Saucepan, avant
    sa publication. Si la suite échoue, l'appelant sait qu'il ne faut surtout
    pas la recréer au cycle suivant — seulement la republier.
    """
    import json as _json

    open_editor(driver, settings_url, log)

    # 0. Repartir d'un brouillon vierge : l'éditeur conserve celui du bot
    #    précédent, avatar compris.
    reset_draft(driver, log)

    # 1. L'avatar d'abord. Saucepan n'active « Restore Data » que si le JSON
    #    passe toute sa validation, image comprise — et l'identifiant d'image
    #    n'existe qu'une fois le fichier déposé dans le formulaire.
    if image_path:
        go_to_editor_page(driver, settings_url, "profile", log)
        try:
            avatar_mod.upload(driver, image_path, log)
        except avatar_mod.AvatarError as exc:
            log(f"⚠ Avatar non déposé : {exc} — l'import sera probablement refusé.")
        go_to_editor_page(driver, settings_url, "settings", log)

    # 2. On récupère le backup que Saucepan produit de lui-même : il porte
    #    l'image qu'on vient de déposer et les champs qu'on ne traduit pas.
    base = read_own_backup(driver, log)
    if base.get("image"):
        log("Image reprise du backup Saucepan.")

    merged = convert.merge_onto_base(base, _json.loads(backup_json_text))
    payload = _json.dumps(merged, ensure_ascii=False, indent=2)

    paste_backup(driver, payload, log)

    if dry_run:
        log("SIMULATION — arrêt avant « Restore Data ». Rien n'a été modifié.")
        return {"dry_run": True, "url": driver.url()}

    log("Clic sur « Restore Data ».")
    driver.click_label("Restore Data")
    driver.page.wait_for_timeout(2000)

    # Saucepan affiche ses refus sous « Validation errors: ». Un refus portant
    # uniquement sur l'image n'est pas bloquant : l'avatar est déposé juste
    # après, par le formulaire.
    errors = driver.validation_errors()
    if errors and not convert.only_image_missing(errors):
        raise DriverError(f"Saucepan a refusé l'import —\n{errors}")
    if errors:
        log("Seule l'image manque à ce stade — dépôt de l'avatar en cours.")

    go_to_editor_page(driver, settings_url, "publish", log)

    # Saucepan refuse de *créer* une companion directement en public : le
    # bouton « Create » ne déclenche alors aucune requête, sans le moindre
    # message. On crée donc toujours en privé, puis on republie si nécessaire.
    set_visibility(driver, "private", log)
    label = save(driver, log)
    if on_created:
        on_created(driver.url())

    if access_level != "private":
        log(f"Passage en « {access_level} » sur la companion enregistrée.")
        go_to_editor_page(driver, driver.url(), "publish", log)
        set_visibility(driver, access_level, log)
        publish_and_verify(driver, access_level, log)

    return {"dry_run": False, "url": driver.url(), "saved_with": label}
