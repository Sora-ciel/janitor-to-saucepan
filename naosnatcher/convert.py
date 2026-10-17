"""Conversion d'une fiche Janitor vers le format « Companion Backup » Saucepan.

Les deux schémas sont connus par observation directe :

**Janitor** — réponse de `/hampter/characters/:id`, interceptée sur le compte
(échantillon dans `data/janitor_api_sample.json`) :
    name, chat_name, description, personality, scenario, example_dialogs,
    first_message, first_messages[], is_nsfw, is_public, tags[], custom_tags[],
    avatar, creator_name, id …

**Saucepan** — règles de validation que le site a renvoyées en refusant un
premier import :
    name, display_name, card, short_description, full_description,
    example_dialogue, tags[] (énumération fermée de 540 valeurs), fandom_tags[],
    sus, very_sus, image, access_level, starting_scenarios[] …

Les deux vocabulaires **diffèrent** : `personality` devient `card`,
`first_messages[]` devient `starting_scenarios[]`, `is_public` devient
`access_level`, `is_nsfw` devient `sus`. C'est donc une vraie traduction,
champ par champ, et non un passage direct.
"""

import json
import os
import re
from datetime import datetime

from . import config
from . import htmlmd
from . import housestyle

BACKUP_FORMAT_VERSION = 4

# Gabarit exact du format « Companion Backup », relevé en cliquant
# « Backup Companion » sur une companion neuve (`data/saucepan_backup_sample.json`).
#
# Les 34 clés doivent **toutes** être présentes. Le validateur de Saucepan
# distingue `null` (accepté) de la clé absente : c'est ce que signifiaient ses
# messages « expected string, received undefined ». Un objet partiel laisse
# « Restore Data » désactivé, sans le moindre message d'erreur — d'où
# l'importance de partir de ce gabarit complet plutôt que d'ajouter les champs
# un à un.
SAUCEPAN_TEMPLATE = {
    "id": None,
    "name": "",
    "display_name": "",
    "card": "",
    "short_description": "",
    "full_description": "",
    "example_dialogue": None,
    "starting_scenarios": [],
    "tags": [],
    "fandom_tags": [],
    "access_level": "private",
    "sus": False,
    "very_sus": False,
    "image": None,
    "image_crop_x": None,
    "image_crop_y": None,
    "image_crop_zoom": None,
    "portraits": [],
    "unlocked_portraits": True,
    "locked_starting_message": False,
    "open_definition": False,
    "hidden_fields": 28,
    "external_model_policy": "vetted_only",
    "formatting_instructions": None,
    "advanced_prompt": None,
    "temperature_offset_percentage": 0,
    "suppress_companion_profile_banner": False,
    "companion_profile_banner_crop_x": None,
    "companion_profile_banner_crop_y": None,
    "companion_profile_banner_crop_zoom": None,
    "companion_profile_banner_very_sus": False,
    "default_profile_banner_collection_image_crop_x": None,
    "default_profile_banner_collection_image_crop_y": None,
    "default_profile_banner_collection_image_crop_zoom": None,
}

_TAGS_FILE = config.TAGS_FILE

ACCESS_LEVELS = ("public", "unlisted", "private", "development")

# Les avatars Janitor sont servis depuis ce préfixe ; l'API ne donne que le
# nom de fichier.
JANITOR_MEDIA_BASE = "https://ella.janitorai.com/bot-avatars/"

# Limite imposée par Saucepan : « Short description cannot be longer than 140
# characters ». Janitor n'a qu'un champ `description`, souvent bien plus long,
# d'où la troncature.
SHORT_DESCRIPTION_MAX = 140


# Réglages de publication appliqués à chaque companion. Ils font partie du
# format de backup : les poser ici évite d'aller les cliquer un à un dans
# l'éditeur, pour chacun des bots transférés.
#
#   open_definition          « Definition Visibility » → Open
#   hidden_fields            masque des champs masqués ; 0 = aucun
#   locked_starting_message  « Lock Starting Message » → activé
#   external_model_policy    « External Model Access » → Vetted only
#
# Modifiables dans data/settings.json, sous la clé « companion_defaults ».
PUBLISH_DEFAULTS = {
    "open_definition": True,
    "hidden_fields": 0,
    "locked_starting_message": True,
    "external_model_policy": "vetted_only",
}


def publish_defaults():
    from . import state                      # import tardif : évite un cycle
    overrides = state.load_settings().get("companion_defaults") or {}
    merged = dict(PUBLISH_DEFAULTS)
    merged.update({k: v for k, v in overrides.items() if k in PUBLISH_DEFAULTS})
    return merged


def valid_tags():
    try:
        with open(_TAGS_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


def _clean_text(value):
    if not isinstance(value, str):
        return value
    return re.sub(r"\r\n?", "\n", value).strip()


def avatar_url(janitor):
    """URL complète de l'avatar Janitor, ou None."""
    name = janitor.get("avatar") or janitor.get("raw_avatar")
    if not name or not isinstance(name, str):
        return None
    if name.startswith("http"):
        return name
    return JANITOR_MEDIA_BASE + name.lstrip("/")


# Saucepan refuse un import sans description ni tag. Quand Janitor ne fournit
# ni l'une ni l'autre, on se rabat sur ce qu'on a plutôt que d'inventer : le
# texte de la fiche, puis le nom. Pour les tags, « unknown » fait partie de
# l'énumération et signifie précisément « non catégorisé ».
FALLBACK_TAG = "unknown"


def strip_html(text):
    """Retire le balisage HTML et rend les entités courantes.

    Janitor stocke ses descriptions en HTML (`<p style="…">…</p>`). La
    description courte de Saucepan est un champ en texte brut, limité à 140
    caractères : y laisser les balises les gaspillerait et afficherait du code.
    """
    if not isinstance(text, str):
        return text
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    for entity, char in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"),
                         ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")):
        text = text.replace(entity, char)
    return re.sub(r"[ \t]+", " ", text).strip()


def _truncate(text, limit):
    """Tronque sans couper un mot en deux, et le signale par une ellipse."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit - 1]
    space = cut.rfind(" ")
    if space > limit * 0.6:          # on ne coupe au mot que si ça reste lisible
        cut = cut[:space]
    return cut.rstrip(" .,;:—-") + "…"


def _first_line(text, limit=SHORT_DESCRIPTION_MAX):
    for line in (text or "").split("\n"):
        line = re.sub(r"^#+\s*", "", line).strip()
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        if line:
            return _truncate(line, limit)
    return ""


def _short_description(janitor):
    """Janitor n'a qu'un `description` ; Saucepan en attend deux.

    On prend la première phrase utile comme description courte, ce qui
    reproduit l'usage observé (l'accroche reprise en tête du texte long).
    """
    full = htmlmd.to_plain_text(_clean_text(janitor.get("description") or ""))
    if not full:
        return ""
    return _first_line(full) or _truncate(full, SHORT_DESCRIPTION_MAX)


def short_name(title):
    """Déduit un nom court d'un titre de bot, quand Janitor n'en donne pas.

    Les titres suivent presque toujours la forme « Personnage | Variante » :
    on garde le premier segment, qui est le nom du personnage.
    """
    if not title:
        return ""
    first = re.split(r"\s*[|/•·—–-]\s*", title, maxsplit=1)[0].strip()
    return (first or title).strip()


# ── Description courte (l'aperçu affiché sur les listes) ────────────────────

def preview_from_markdown(markdown, fallback=""):
    """Choisit l'aperçu : le premier paragraphe qui suit le titre.

    S'il dépasse la limite de Saucepan, on ne le tronque pas — un aperçu coupé
    au milieu d'une phrase se lit mal. On retombe alors sur le titre lui-même,
    et l'on signale le cas pour que l'auteur écrive un vrai résumé.

    Renvoie (texte, dépassement) où `dépassement` est None ou la longueur du
    paragraphe écarté.
    """
    # On raisonne par blocs séparés par une ligne vide, et **uniquement sur le
    # début du document**. Chercher un titre n'importe où menait à prendre
    # celui d'une section lointaine — « Author's note » ou « Suggestion Box » —
    # quand la fiche n'avait pas de titre en bonne et due forme au sommet.
    blocks = [b.strip() for b in re.split(r"\n\s*\n", markdown or "")
              if b.strip() and not SEPARATOR.fullmatch(b.strip())]
    if not blocks:
        return _truncate(fallback, SHORT_DESCRIPTION_MAX), None

    title, paragraph = "", ""

    # Le titre peut être un vrai titre Markdown, ou simplement du gras — et le
    # texte peut le suivre immédiatement, sur la même ligne, quand la source
    # HTML ne mettait pas de saut de ligne après le `<strong>`.
    head = re.match(r"^#{1,6}\s*\*\*(.+?)\*\*\s*(.*)$", blocks[0], re.S) \
        or re.match(r"^\*\*(.+?)\*\*\s*(.*)$", blocks[0], re.S) \
        or re.match(r"^#{1,6}\s*(.+?)\s*$()", blocks[0], re.S)

    if head:
        title = head.group(1).strip()
        remainder = head.group(2).strip()
        paragraph = remainder or (blocks[1] if len(blocks) > 1 else "")
    else:
        paragraph = blocks[0]

    # Un bloc qui n'est qu'un intitulé (« **Special Notes** ») ne fait pas un
    # aperçu : on prend le suivant.
    if paragraph and re.fullmatch(r"\*\*.+?\*\*[:：]?", paragraph.strip()):
        index = blocks.index(paragraph) if paragraph in blocks else 0
        paragraph = blocks[index + 1] if index + 1 < len(blocks) else ""

    clean_title = re.sub(r"[*#]+", "", title).strip()
    clean_paragraph = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", paragraph)
    clean_paragraph = re.sub(r"[*#>]+", "", clean_paragraph).strip()

    if clean_paragraph and len(clean_paragraph) <= SHORT_DESCRIPTION_MAX:
        return clean_paragraph, None

    overflow = len(clean_paragraph) if clean_paragraph else None

    if clean_title and len(clean_title) <= SHORT_DESCRIPTION_MAX:
        return clean_title, overflow

    return _truncate(clean_paragraph or clean_title or fallback,
                     SHORT_DESCRIPTION_MAX), overflow


SEPARATOR = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")


def _tag_name(tag):
    """Un tag Janitor est soit une chaîne, soit un objet {name|slug|…}."""
    if isinstance(tag, str):
        return tag.strip()
    if isinstance(tag, dict):
        for key in ("slug", "name", "tag", "title"):
            if isinstance(tag.get(key), str) and tag[key].strip():
                return tag[key].strip()
    return ""


# Les deux sites nomment parfois différemment la même notion. Sans ces
# équivalences, des tags parfaitement valides seraient écartés — « submissive »
# chez Janitor s'appelle « sub » chez Saucepan.
#
# Volontairement limité aux synonymes évidents : mieux vaut perdre un tag que
# d'en inventer un qui trahirait le bot.
TAG_SYNONYMS = {
    "submissive": "sub",
    "dominant": "dom",
    "nonbinary": "non_binary",
    "gay": "mlm",
    "lesbian": "wlw",
    "bisexual": "bi",
    "female": "female",
    "comfort_hurt": "hurt_comfort",
    "slice_of_life": "slice_of_life",
    "sci_fi": "space",
    "yandere": "yandere",
}


def _normalise_tag(name):
    """Rapproche un tag Janitor de la forme attendue par Saucepan."""
    slug = name.strip().lower().replace(" ", "_").replace("-", "_")
    return TAG_SYNONYMS.get(slug, slug)


def collect_tags(janitor):
    """Tags Janitor → tags Saucepan. Renvoie (retenus, écartés)."""
    allowed = valid_tags()
    kept, dropped = [], []
    for source in ("tags", "custom_tags"):
        for raw in janitor.get(source) or []:
            name = _tag_name(raw)
            if not name:
                continue
            candidate = _normalise_tag(name)
            if candidate in kept:
                continue
            if allowed and candidate not in allowed:
                dropped.append(name)
            else:
                kept.append(candidate)
    return kept, dropped


def dropped_tags(janitor):
    return collect_tags(janitor)[1]


def _starting_scenarios(janitor):
    """`first_messages[]` de Janitor → `starting_scenarios[]` de Saucepan."""
    messages = janitor.get("first_messages")
    if not messages:
        single = janitor.get("first_message")
        messages = [single] if single else []
    out = []
    for m in messages:
        if isinstance(m, dict):
            m = m.get("message") or m.get("text") or ""
        text = _clean_text(m or "")
        if text:
            out.append({"title": None, "message": text, "portrait_id": None})
    return out


def access_level(janitor):
    """`is_public` de Janitor → énumération `access_level` de Saucepan.

    Conservateur : on ne rend public que sur un `is_public` explicitement vrai.
    """
    # Une fiche Saucepan (ré-import) porte déjà access_level.
    existing = janitor.get("access_level")
    if isinstance(existing, str) and existing.strip().lower() in ACCESS_LEVELS:
        return existing.strip().lower()
    return "public" if janitor.get("is_public") is True else "private"


def is_public(janitor):
    return access_level(janitor) == "public"


def janitor_to_saucepan(janitor, image=None):
    """Traduit une fiche Janitor en objet de backup Saucepan.

    `image` : l'objet image côté Saucepan. Saucepan refuse tout import sans
    image de profil, et l'avatar Janitor n'est qu'un nom de fichier sur son
    propre CDN — il faut donc l'y téléverser au préalable. Voir avatar_url().
    """
    # On part du gabarit complet : toutes les clés attendues sont présentes,
    # avec les valeurs par défaut de Saucepan, puis on écrase celles qu'on sait
    # traduire. Un objet partiel serait silencieusement refusé.
    out = dict(SAUCEPAN_TEMPLATE)

    # Les deux sites emploient ces deux champs en sens inverse :
    #
    #   Janitor   name = « Ryomen Sukuna | The Butcher »   chat_name = « Sukuna »
    #   Saucepan  display_name = le titre complet       name = le nom court
    #
    # C'est `name` qui apparaît dans la conversation, et `display_name` en
    # tête de fiche : les intervertir donne un bot qui s'annonce avec son
    # titre entier à chaque réplique.
    title = _clean_text(janitor.get("name") or "")
    out["display_name"] = title
    out["name"] = _clean_text(janitor.get("chat_name") or "") or short_name(title)

    # Le cœur de la définition : `personality` chez Janitor, `card` chez
    # Saucepan.
    out["card"] = _clean_text(janitor.get("personality") or janitor.get("card") or "")

    # Janitor a un champ `scenario` distinct ; le format Saucepan n'en a pas.
    # Le laisser tomber ferait perdre du contenu réel sans rien signaler : on
    # l'ajoute donc à la définition, sous un intertitre qui garde la couture
    # visible et permet de le retrouver.
    scenario = _clean_text(janitor.get("scenario") or "")
    if scenario and scenario not in out["card"]:
        out["card"] = (out["card"] + "\n\n> Scenario\n\n" + scenario).strip()

    # Saucepan exige les deux descriptions non vides. Beaucoup de bots Janitor
    # n'ont qu'un `description`, parfois vide : on se rabat sur la définition
    # puis sur le nom, faute de quoi l'import serait tout simplement refusé.
    # Janitor stocke la description en HTML enrichi ; Saucepan affiche du
    # Markdown. Recopier le HTML tel quel donnerait une fiche pleine de balises.
    description = housestyle.apply(
        htmlmd.to_markdown(_clean_text(janitor.get("description") or "")))
    out["full_description"] = description or out["card"] or out["display_name"]

    preview, overflow = preview_from_markdown(
        out["full_description"], fallback=out["display_name"] or out["name"])
    out["short_description"] = preview or out["display_name"] or out["name"]

    # Attention au pluriel : `example_dialogs` chez Janitor,
    # `example_dialogue` chez Saucepan.
    out["example_dialogue"] = _clean_text(janitor.get("example_dialogs") or "")

    out["starting_scenarios"] = _starting_scenarios(janitor)
    out["access_level"] = access_level(janitor)
    out["sus"] = bool(janitor.get("is_nsfw") or janitor.get("sus"))
    out["very_sus"] = bool(janitor.get("very_sus"))
    out["tags"], _ = collect_tags(janitor)
    if not out["tags"]:
        # « At least one tag is required » : sans tag, l'import est refusé.
        out["tags"] = [FALLBACK_TAG]

    # Réglages de publication : définition ouverte, message de départ
    # verrouillé, modèles externes limités aux vérifiés.
    out.update(publish_defaults())

    if image is not None:
        out["image"] = image

    out["_naosnatcher"] = {
        "format_version": BACKUP_FORMAT_VERSION,
        "source": "janitorai",
        "source_id": janitor.get("id"),
        "avatar_url": avatar_url(janitor),
        "imported_at": datetime.now().isoformat(timespec="seconds"),
        # Longueur du paragraphe écarté quand il dépassait la limite ; None
        # sinon. Sert au rapport envoyé par `python -m naosnatcher.notify`.
        "preview_overflow": overflow,
    }

    return out


def merge_onto_base(base, companion):
    """Superpose nos champs traduits à un backup produit par Saucepan.

    Pourquoi ce détour : Saucepan n'active « Restore Data » que si le JSON
    passe toute sa validation, image comprise — et l'identifiant d'image
    n'existe qu'après un dépôt dans le formulaire. On dépose donc l'avatar
    d'abord, on demande à Saucepan son propre backup (qui contient dès lors
    l'image et le bon gabarit), et on n'écrase que ce qu'on sait traduire.

    Tout ce qu'on ne traduit pas — recadrages, `hidden_fields`, réglages de
    bannière — reste tel que Saucepan l'a écrit.
    """
    merged = dict(base)
    for key, value in companion.items():
        if key.startswith("_"):
            continue
        # L'image vient du backup : notre marqueur ne doit pas l'écraser.
        if key == "image":
            if isinstance(value, dict) and value.get("pending_upload"):
                continue
            if value is None and base.get("image") is not None:
                continue
        merged[key] = value
    return merged


def image_requirement(saucepan_obj):
    """Vérifie qu'une image de profil sera bien fournie.

    Trois cas acceptés : un identifiant Saucepan, une URL, ou le marqueur
    `pending_upload` — l'avatar a été rapatrié et sera déposé dans le
    formulaire, l'identifiant n'existant qu'après ce dépôt.
    """
    img = saucepan_obj.get("image")
    if isinstance(img, dict) and (img.get("id") or img.get("pending_upload")):
        return None
    if isinstance(img, str) and img.strip():
        return None
    return ("Aucune image de profil : Saucepan refuse l'import "
            "(« Profile image is required »).")


def validate(saucepan_obj):
    """Rejoue localement les règles de validation connues de Saucepan.

    Évite un aller-retour dans le navigateur pour une erreur visible tout de
    suite. Renvoie la liste des problèmes ; vide = conforme.
    """
    problems = []

    if not saucepan_obj.get("name"):
        problems.append("name : obligatoire")

    for key in ("sus", "very_sus"):
        if not isinstance(saucepan_obj.get(key), bool):
            problems.append(f"{key} : booléen attendu")

    if not isinstance(saucepan_obj.get("example_dialogue"), str):
        problems.append("example_dialogue : chaîne attendue")

    short = saucepan_obj.get("short_description") or ""
    if len(short) > SHORT_DESCRIPTION_MAX:
        problems.append(
            f"short_description : {len(short)} caractères, "
            f"maximum {SHORT_DESCRIPTION_MAX}")
    if not short:
        problems.append("short_description : obligatoire")

    if not saucepan_obj.get("full_description"):
        problems.append("full_description : obligatoire")

    if not saucepan_obj.get("tags"):
        problems.append("tags : au moins un tag est requis")

    if saucepan_obj.get("access_level") not in ACCESS_LEVELS:
        problems.append(f"access_level : attendu l'un de {'|'.join(ACCESS_LEVELS)}")

    allowed = valid_tags()
    if allowed:
        for i, t in enumerate(saucepan_obj.get("tags") or []):
            if t not in allowed:
                problems.append(f"tags.{i} : « {t} » hors énumération")

    missing_image = image_requirement(saucepan_obj)
    if missing_image:
        problems.append(missing_image)

    return problems


def to_backup_string(saucepan_obj):
    """Le texte exact à coller dans « Paste Companion Backup ».

    Le marqueur `pending_upload` est retiré : il ne sert qu'à notre validation
    locale, et Saucepan refuserait un objet `image` qu'il ne reconnaît pas.
    L'avatar est déposé séparément, par le formulaire.
    """
    payload = {k: v for k, v in saucepan_obj.items() if not k.startswith("_")}

    # L'avatar est déposé par le formulaire, pas par le JSON. On remet la clé
    # à `null` — la valeur d'une companion neuve — plutôt que de la retirer :
    # une clé absente ferait échouer la validation.
    img = payload.get("image")
    if isinstance(img, dict) and img.get("pending_upload"):
        payload["image"] = None

    return json.dumps(payload, ensure_ascii=False, indent=2)


def only_image_missing(error_text):
    """L'erreur renvoyée par Saucepan ne porte-t-elle que sur l'image ?

    Dans ce cas l'import n'est pas à refaire : l'avatar sera déposé par le
    formulaire juste après.
    """
    if not error_text:
        return False
    lines = [l.strip() for l in error_text.splitlines() if l.strip()]
    lines = [l for l in lines if not l.lower().startswith("validation errors")]
    return bool(lines) and all("image" in l.lower() for l in lines)


def _safe_filename(name):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name or "companion")[:80].strip() or "companion"


def save_export(saucepan_obj, janitor_id):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    fname = f"{stamp}_{_safe_filename(saucepan_obj.get('name'))}_{janitor_id}.json"
    path = os.path.join(config.EXPORT_DIR, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(to_backup_string(saucepan_obj))
    return path
