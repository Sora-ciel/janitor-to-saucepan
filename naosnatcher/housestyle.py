"""Mise en forme « maison » des descriptions, après conversion en Markdown.

Ce module fait ce qui était jusqu'ici retouché à la main après chaque import,
d'après deux fiches Saucepan de référence :

  · un séparateur `---` entre chaque section ;
  · les avertissements encadrés d'émojis : `### **⚠️ TRIGGER WARNINGS ⚠️**` ;
  · l'encart promotionnel Patreon retiré (il renvoie au compte Janitor) ;
  · la signature « toutes mes plateformes » ajoutée en fin de fiche ;
  · le crédit de l'artiste laissé en tout dernier.

Contrairement à `htmlmd.py`, qui traduit fidèlement un format vers un autre,
il s'agit ici de **choix éditoriaux**. Ils se règlent donc sans toucher au
code, via `data/housestyle.json` : le fichier est créé au premier lancement
avec les valeurs ci-dessous et relu à chaque conversion.
"""

import json
import os
import re

from . import config

CONFIG_FILE = os.path.join(config.DATA_DIR, "housestyle.json")

# Valeurs **neutres** : c'est ce que reçoit toute nouvelle installation. Les
# choix propres à un auteur — sa signature, ses liens, les encarts qu'il
# retire — vont dans son `data/housestyle.json`, jamais ici : ce fichier part
# dans l'exécutable distribué, et chacun recevrait sinon la signature d'un
# autre au bas de ses fiches.
#
# Exemple de réglages personnels, à placer dans data/housestyle.json :
#   "footer": "👉 Tous mes liens : [Link Hub](https://…)",
#   "drop_sections": ["join my patreon"],
#   "drop_lines": ["litt\\.ly", "find all my links"]
DEFAULTS = {
    # Sections supprimées : comparaison sur le titre, sans tenir compte de la
    # casse. Une section va d'un titre `###` au titre suivant.
    "drop_sections": [],

    # Titres décorés d'émojis. Clé = fragment cherché dans le titre.
    "decorate_headings": {
        "trigger warnings": "⚠️ {title} ⚠️",
    },

    # Ajoutée avant le crédit de l'artiste, si elle n'est pas déjà présente.
    "footer": "",

    # Séparateur inséré entre les sections.
    "section_separator": "---",

    # Lignes supprimées où qu'elles se trouvent (expressions régulières,
    # insensibles à la casse).
    "drop_lines": [],

    # Mise en forme active ou non.
    "enabled": True,
}

HEADING = re.compile(r"^###\s+\*\*(.+?)\*\*\s*$", re.M)

# Le crédit peut être enrobé de Markdown et précédé d'un ornement variable :
# `***⤷ Artist: …***`, `↯ Artist: …`, `> Artist: …`. On accepte donc n'importe
# quels caractères non alphanumériques avant le mot.
ARTIST_LINE = re.compile(r"^\s*[^A-Za-z0-9]{0,8}\s*Artist\s*:", re.I)

# Ligne ne contenant qu'un séparateur : les séparateurs d'origine sont retirés
# puis réinsérés proprement, sinon supprimer une section laisserait le sien
# derrière elle et l'on obtiendrait « --- --- ».
SEPARATOR_ONLY = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")


def load_config():
    """Réglages éditoriaux, créés au premier appel puis modifiables à la main."""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        merged = dict(DEFAULTS)
        merged.update(saved)
        return merged
    except (OSError, ValueError):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(DEFAULTS, f, ensure_ascii=False, indent=2)
        except OSError:
            pass
        return dict(DEFAULTS)


def split_sections(markdown):
    """Découpe en [(titre ou None, contenu)], le préambule ayant un titre None."""
    matches = list(HEADING.finditer(markdown))
    if not matches:
        return [(None, markdown)]

    sections = []
    if matches[0].start() > 0:
        preamble = markdown[:matches[0].start()].strip()
        if preamble:
            sections.append((None, preamble))

    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        body = markdown[match.end():end].strip()
        sections.append((match.group(1).strip(), body))
    return sections


def _decorate(title, rules):
    for needle, pattern in rules.items():
        if needle.lower() in title.lower():
            # On n'ajoute pas deux fois la décoration.
            if pattern.replace("{title}", "").strip() and \
                    pattern.format(title="").strip("* ").strip() in title:
                return title
            already = all(part in title for part in
                          pattern.split("{title}") if part.strip())
            return title if already else pattern.format(title=title)
    return title


def apply(markdown, settings=None):
    """Applique la mise en forme maison à une description déjà en Markdown."""
    cfg = settings or load_config()
    if not cfg.get("enabled", True) or not markdown:
        return markdown

    drop = {d.strip().lower() for d in cfg.get("drop_sections") or []}
    decorate = cfg.get("decorate_headings") or {}
    separator = cfg.get("section_separator") or "---"

    noise = [re.compile(p, re.I) for p in cfg.get("drop_lines") or []]

    def clean_body(body):
        lines = []
        for line in body.split("\n"):
            if SEPARATOR_ONLY.match(line):
                continue
            if line.strip() and any(p.search(line) for p in noise):
                continue
            lines.append(line)
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()

    kept = []
    for title, body in split_sections(markdown):
        body = clean_body(body)
        if title is None:
            if body:
                kept.append((None, body))
            continue
        if title.strip().lower() in drop:
            continue
        kept.append((_decorate(title, decorate), body))

    # Une section vidée de tout contenu n'a plus lieu d'être.
    kept = [(t, b) for t, b in kept if b or t is None]

    # Le crédit de l'artiste doit rester la toute dernière ligne : on le met de
    # côté pour le replacer après la signature.
    artist = None
    if kept:
        title, body = kept[-1]
        lines = body.split("\n")
        while lines and not lines[-1].strip():
            lines.pop()
        if lines and ARTIST_LINE.match(lines[-1]):
            artist = lines.pop().strip()
            kept[-1] = (title, "\n".join(lines).strip())

    parts = []
    for index, (title, body) in enumerate(kept):
        if index:
            parts.append(separator)
        if title:
            parts.append(f"### **{title}**")
        if body:
            parts.append(body)

    text = "\n\n".join(p for p in parts if p)

    footer = (cfg.get("footer") or "").strip()
    if footer and footer.split("](")[0][:40] not in text:
        text += "\n\n" + footer
    if artist:
        text += "\n\n" + artist

    return re.sub(r"\n{3,}", "\n\n", text).strip()
