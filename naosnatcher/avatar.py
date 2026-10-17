"""Récupération de l'avatar Janitor et téléversement vers Saucepan.

Saucepan refuse tout import de companion sans image de profil
(« Profile image is required »), et Janitor ne fournit qu'un nom de fichier
servi par son propre CDN. Il faut donc rapatrier l'image puis la redéposer.

Le CDN a été relevé sur la page d'édition en direct :
    https://ella.janitorai.com/bot-avatars/<nom>.webp[?width=N]
Sans paramètre `width`, on obtient l'original.
"""

import os
import re

import requests

from . import config

MEDIA_BASE = "https://ella.janitorai.com/bot-avatars/"

CACHE_DIR = os.path.join(config.DATA_DIR, "avatars")
os.makedirs(CACHE_DIR, exist_ok=True)

# Certains CDN renvoient une page d'erreur en 200 ; on vérifie le type MIME.
IMAGE_TYPES = ("image/webp", "image/png", "image/jpeg", "image/gif", "image/avif")

_HEADERS = {
    "User-Agent": config.USER_AGENT,
    "Referer": config.JANITOR_ORIGIN + "/",
}


class AvatarError(RuntimeError):
    pass


def avatar_url(janitor, width=None):
    """URL complète de l'avatar d'une fiche Janitor, ou None."""
    name = janitor.get("avatar") or janitor.get("raw_avatar")
    if not name or not isinstance(name, str):
        return None
    if name.startswith("http"):
        return name
    url = MEDIA_BASE + name.lstrip("/")
    return f"{url}?width={width}" if width else url


def _extension(content_type, url):
    for mime, ext in (("webp", ".webp"), ("png", ".png"),
                      ("jpeg", ".jpg"), ("gif", ".gif"), ("avif", ".avif")):
        if mime in (content_type or ""):
            return ext
    match = re.search(r"\.(webp|png|jpe?g|gif|avif)", url, re.I)
    return f".{match.group(1).lower()}" if match else ".webp"


def download(janitor, log=print):
    """Rapatrie l'avatar en cache local et renvoie son chemin.

    Lève AvatarError si la fiche n'a pas d'avatar ou si le CDN ne renvoie pas
    une image — mieux vaut un échec explicite qu'un fichier corrompu déposé
    dans le formulaire de Saucepan.
    """
    url = avatar_url(janitor)
    if not url:
        raise AvatarError("Cette fiche Janitor n'a pas d'avatar.")

    try:
        response = requests.get(url, headers=_HEADERS, timeout=30)
    except requests.RequestException as exc:
        raise AvatarError(f"Téléchargement impossible : {exc}") from exc

    if response.status_code != 200:
        raise AvatarError(f"CDN Janitor : HTTP {response.status_code} sur {url}")

    content_type = (response.headers.get("content-type") or "").lower()
    if not any(t in content_type for t in IMAGE_TYPES):
        raise AvatarError(
            f"Le CDN a renvoyé « {content_type or 'type inconnu'} » "
            "au lieu d'une image."
        )

    stem = re.sub(r"[^A-Za-z0-9_-]", "_", str(janitor.get("id") or "avatar"))[:60]
    path = os.path.join(CACHE_DIR, stem + _extension(content_type, url))
    with open(path, "wb") as f:
        f.write(response.content)

    log(f"Avatar récupéré ({len(response.content) // 1024} Ko) → {path}")
    return path


# ── Dépôt côté Saucepan ─────────────────────────────────────────────────────

# Le champ d'avatar vit sur /editor/new/profile et porte un identifiant
# stable — relevé sur une capture réelle :
#   <input id="profile-image" type="file"
#          accept="image/png,image/jpg,image/jpeg,image/gif,image/webp">
# À ne pas confondre avec #companion-profile-banner, la bannière, présente sur
# la même page et acceptant exactement les mêmes types.
AVATAR_INPUT_ID = "#profile-image"
BANNER_INPUT_ID = "#companion-profile-banner"

IMAGE_INPUT_SELECTORS = [
    AVATAR_INPUT_ID,
    'input[type="file"][accept*="image"]',
    'input[type="file"][accept*="webp"]',
]

# Libellés menant au choix d'une image, relevés sur l'éditeur.
IMAGE_BUTTON_LABELS = ["Upload", "Choose from library", "Upload image",
                       "Change image", "Add image"]


def find_image_input(driver):
    """Sélecteur du champ fichier acceptant une image, ou None.

    On écarte explicitement le champ de la section Backup/Restore, qui
    n'accepte que du JSON.
    """
    for selector in IMAGE_INPUT_SELECTORS:
        if driver.page.query_selector(selector) is not None:
            return selector

    # Dernier recours : un input fichier qui accepte des images sans être la
    # bannière — la confondre avec l'avatar donnerait une companion sans photo
    # de profil mais avec une belle bannière.
    inputs = driver.page.query_selector_all('input[type="file"]')
    for index, el in enumerate(inputs):
        accept = (el.get_attribute("accept") or "").lower()
        element_id = (el.get_attribute("id") or "").lower()
        if "json" in accept or "image" not in accept:
            continue
        if "banner" in element_id:
            continue
        return f'input[type="file"] >> nth={index}'
    return None


def upload(driver, image_path, log=print):
    """Dépose l'image dans le formulaire de la companion.

    Renvoie True si un champ a reçu le fichier. Le champ image ne se trouve pas
    sur la page des réglages : appelez ceci sur la page de l'éditeur qui porte
    l'avatar.
    """
    if not os.path.isfile(image_path):
        raise AvatarError(f"Fichier introuvable : {image_path}")

    selector = find_image_input(driver)

    if selector is None:
        # Le champ est parfois monté seulement après un clic sur « Upload ».
        for label in IMAGE_BUTTON_LABELS:
            state = driver.button_state(label)
            if state.get("present") and not state.get("disabled"):
                log(f"Ouverture du sélecteur via « {label} ».")
                driver.click_label(label)
                driver.page.wait_for_timeout(1200)
                selector = find_image_input(driver)
                if selector:
                    break

    if selector is None:
        raise AvatarError(
            "Aucun champ d'image trouvé sur cette page de l'éditeur. "
            "L'éditeur Saucepan est découpé en plusieurs pages : vérifiez que "
            "celle portant l'avatar est bien ouverte."
        )

    driver.page.set_input_files(selector, image_path)
    log(f"Image déposée dans {selector}.")
    driver.page.wait_for_timeout(2500)
    return True
