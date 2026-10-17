"""Cartes de personnage : l'avatar d'un bot, avec sa fiche intégrée au PNG.

C'est le format « Character Card » que lisent Janitor, SillyTavern, Chub et la
plupart des sites du genre : une image PNG ordinaire, dont un bloc de texte
`chara` porte la fiche en JSON encodé en Base64. On écrit aussi le bloc `ccv3`
(version 3 du format) pour les outils récents ; les anciens l'ignorent.

Reprend l'ancien outil `references/legacy-tools/…/ecrire_metadata_gui.py`, mais
alimenté directement par la fiche Janitor plutôt que par une saisie à la main.
"""

import base64
import json
import os
import re

from . import avatar as avatar_mod
from . import config, htmlmd

# Un identifiant de bot Janitor : un UUID, seul ou en tête de l'URL
# (« /characters/<uuid>_nom-du-bot »).
CHAR_ID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


class CardError(RuntimeError):
    pass


def char_id_from(text):
    """Extrait l'identifiant d'un bot d'une URL Janitor (ou d'un UUID nu)."""
    found = CHAR_ID.search(text or "")
    if not found:
        raise CardError(
            "Aucun identifiant de bot dans cette adresse. Collez l'URL de la "
            "page du bot, du type https://janitorai.com/characters/…"
        )
    return found.group(0).lower()


def _tag_names(fiche):
    names = []
    for source in ("tags", "custom_tags"):
        for tag in fiche.get(source) or []:
            name = tag.get("name") if isinstance(tag, dict) else tag
            if isinstance(name, str) and name.strip() and name.strip() not in names:
                names.append(name.strip())
    return names


def card_data(fiche):
    """Fiche Janitor → champs d'une carte de personnage.

    Les correspondances suivent l'**importeur de Janitor**, relevé en direct
    en déposant une carte sur le formulaire de création :

        carte.personality   → case « Personality » (la définition)
        carte.description   → présentation publique (éditeur riche)
        carte.creator_notes → ignoré

    C'est l'inverse de la convention SillyTavern, où `description` porte la
    définition. Suivre cette convention envoyait la définition dans la
    présentation publique et laissait « Personality » vide.

    La présentation reste en **HTML d'origine** : l'éditeur riche de Janitor
    l'affiche fidèlement (centrage, gras), alors qu'il montre le Markdown tel
    quel, symboles `###` et `**` compris, le tout fondu en un seul paragraphe.
    """
    greetings = [g for g in (fiche.get("first_messages") or []) if g]
    first = fiche.get("first_message") or (greetings[0] if greetings else "")
    alternates = [g for g in greetings if g != first]

    return {
        "name": fiche.get("chat_name") or fiche.get("name") or "",
        # Champ propre à Janitor, repris de l'ancien outil : le titre complet.
        "chat_name": fiche.get("chat_name") or "",
        "description": fiche.get("description") or "",
        "personality": fiche.get("personality") or "",
        "scenario": fiche.get("scenario") or "",
        "first_mes": first,
        "mes_example": fiche.get("example_dialogs") or "",
        "creator_notes": htmlmd.to_markdown(fiche.get("description") or ""),
        "system_prompt": "",
        "post_history_instructions": "",
        "alternate_greetings": alternates,
        "tags": _tag_names(fiche),
        "creator": fiche.get("creator_name") or "",
        "character_version": "",
        "extensions": {"janitor": _janitor_extension(fiche)},
    }


def _janitor_extension(fiche):
    """Bloc propre à Janitor. Le titre complet y est toujours conservé — c'est
    lui que l'éditeur de cartes relit — mais l'identifiant et l'adresse
    n'existent que pour un vrai bot Janitor : une carte faite à la main
    n'aurait sinon qu'une adresse en « …/characters/None »."""
    ext = {"title": fiche.get("name"), "is_nsfw": fiche.get("is_nsfw")}
    if fiche.get("id"):
        ext["id"] = fiche["id"]
        ext["url"] = config.JANITOR_VIEW_URL.format(char_id=fiche["id"])
    return ext


def _b64(payload):
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def _placeholder(title):
    """Fond neutre portant le nom, pour un bot sans avatar."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (512, 768), (38, 36, 48))
    draw = ImageDraw.Draw(img)
    text = (title or "?")[:40]
    box = draw.textbbox((0, 0), text)
    draw.text(((512 - (box[2] - box[0])) / 2, 370), text, fill=(220, 220, 230))
    return img


def safe_name(text, limit=60):
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text or "").strip()
    return re.sub(r"\s+", " ", text)[:limit].rstrip(" .") or "bot"


def write_card(fiche, image_path=None, log=print, out_dir=None, path=None):
    """Écrit la carte PNG d'une fiche Janitor et renvoie son chemin.

    `image_path` : avatar déjà rapatrié ; à défaut, on le télécharge.
    `path` : fichier de sortie imposé (éditeur de cartes) ; sinon le nom est
    tiré du titre, dans `out_dir`.
    """
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo

    if not image_path and (fiche.get("avatar") or fiche.get("raw_avatar")):
        try:
            image_path = avatar_mod.download(fiche, log)
        except avatar_mod.AvatarError as exc:
            log(f"⚠ Avatar indisponible ({exc}) — carte sur fond neutre.")

    if image_path:
        try:
            with Image.open(image_path) as src:
                src.seek(0)                    # premier plan d'un GIF animé
                img = src.convert("RGBA")
        except OSError as exc:
            raise CardError(f"Avatar illisible : {exc}") from exc
    else:
        img = _placeholder(fiche.get("name"))

    data = card_data(fiche)
    meta = PngInfo()
    meta.add_text("chara", _b64({"spec": "chara_card_v2",
                                 "spec_version": "2.0", "data": data}))
    meta.add_text("ccv3", _b64({"spec": "chara_card_v3", "spec_version": "3.0",
                                "data": dict(data, group_only_greetings=[])}))

    if not path:
        out_dir = out_dir or config.CARDS_DIR
        os.makedirs(out_dir, exist_ok=True)
        stem = safe_name(fiche.get("name") or data["name"])
        # Une carte faite à la main n'a pas d'identifiant Janitor : pas de
        # suffixe « [None] », mais un numéro si le nom est déjà pris.
        if fiche.get("id"):
            path = os.path.join(out_dir, f"{stem} [{str(fiche['id'])[:8]}].png")
        else:
            path = os.path.join(out_dir, f"{stem}.png")
            n = 2
            while os.path.exists(path):
                path = os.path.join(out_dir, f"{stem} ({n}).png")
                n += 1
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    img.save(path, "PNG", pnginfo=meta)
    log(f"🖼 Carte écrite : {path}")
    return path


def read_card(path):
    """Relit la fiche d'une carte (bloc `ccv3` de préférence)."""
    from PIL import Image

    with Image.open(path) as img:
        text = dict(getattr(img, "text", {}) or {})
    raw = text.get("ccv3") or text.get("chara")
    if not raw:
        raise CardError("Aucune fiche intégrée à cette image.")
    return json.loads(base64.b64decode(raw).decode("utf-8"))


# ── Éditeur de cartes : fiche saisie à la main ──────────────────────────────

# Séparateur des messages de départ alternatifs dans l'éditeur. Pas « --- » :
# c'est une règle Markdown courante à l'intérieur même des messages.
GREETING_SEPARATOR = "====="


def text_to_html(text):
    """Présentation saisie → HTML.

    L'éditeur riche de Janitor affiche fidèlement le HTML, mais fond le texte
    brut en un seul paragraphe. Un texte qui contient déjà des balises (une
    présentation reprise d'une carte existante) est conservé tel quel.
    """
    import html

    text = (text or "").strip()
    if not text:
        return ""
    if re.search(r"<(p|br|strong|em|b|i|div|span|h[1-6])\b", text, re.I):
        return text
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return "".join("<p>" + html.escape(p).replace("\n", "<br>") + "</p>"
                   for p in paragraphs)


def html_to_text(value):
    """Inverse de text_to_html, **seulement** pour le HTML simple qu'il produit
    (paragraphes et sauts de ligne). Une présentation riche — centrage, gras,
    venue de Janitor — est rendue telle quelle : la convertir en texte
    perdrait sa mise en forme au prochain enregistrement."""
    import html

    value = value or ""
    tags = re.findall(r"</?([a-zA-Z0-9]+)[^>]*>", value)
    if not tags or any(t.lower() not in ("p", "br") for t in tags) \
            or re.search(r"<p\s+[^>]", value):
        return value
    text = re.sub(r"<br\s*/?>", "\n", value)
    text = re.sub(r"</p>\s*<p>", "\n\n", text)
    text = re.sub(r"</?p>", "", text)
    return html.unescape(text).strip()


def fiche_from_fields(fields):
    """Champs de l'éditeur → fiche au format Janitor, prête pour write_card."""
    greetings = [fields.get("first_message") or ""]
    greetings += list(fields.get("alternate_greetings") or [])
    greetings = [g for g in greetings if g and g.strip()]
    tags = [t.strip() for t in re.split(r"[,\n]", fields.get("tags") or "")
            if t.strip()]
    return {
        "id": None,
        "name": (fields.get("title") or "").strip(),
        "chat_name": (fields.get("chat_name") or "").strip(),
        "personality": fields.get("personality") or "",
        "description": text_to_html(fields.get("description")),
        "scenario": fields.get("scenario") or "",
        "first_message": greetings[0] if greetings else "",
        "first_messages": greetings,
        "example_dialogs": fields.get("example_dialogs") or "",
        "tags": tags,
        "creator_name": (fields.get("creator") or "").strip(),
    }


def fields_from_card(card):
    """Fiche relue d'une carte → champs de l'éditeur.

    Accepte les cartes d'ailleurs. Une carte au format SillyTavern — ou faite
    par une version antérieure de Naosnatcher — range la définition dans
    `description` et laisse `personality` vide : on la remet alors à sa place,
    sans quoi elle repartirait dans la présentation publique.
    """
    data = card.get("data", card) if isinstance(card, dict) else {}
    janitor = (data.get("extensions") or {}).get("janitor") or {}
    personality = data.get("personality") or ""
    description = data.get("description") or ""
    if not personality.strip() and description.strip() \
            and not re.search(r"<(p|br|strong|div|span)\b", description, re.I):
        personality, description = description, ""
    return {
        "title": janitor.get("title") or data.get("name") or "",
        "chat_name": data.get("chat_name") or data.get("name") or "",
        "personality": personality,
        "description": html_to_text(description),
        "scenario": data.get("scenario") or "",
        "first_message": data.get("first_mes") or "",
        "alternate_greetings": [g for g in (data.get("alternate_greetings") or [])
                                if isinstance(g, str)],
        "example_dialogs": data.get("mes_example") or "",
        "tags": ", ".join(t for t in (data.get("tags") or []) if isinstance(t, str)),
        "creator": data.get("creator") or "",
    }
