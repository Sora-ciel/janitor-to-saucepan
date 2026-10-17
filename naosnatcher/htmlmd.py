"""Conversion du HTML de Janitor vers le Markdown attendu par Saucepan.

Janitor stocke les descriptions en HTML enrichi (`<p style="text-align:
center"><strong>…</strong></p>`, `<span style="color: …">`, `<br>`, images
hébergées sur son CDN). Saucepan, lui, affiche du Markdown. Recopier le HTML
tel quel donne une fiche illisible, pleine de balises.

Les règles ci-dessous reproduisent la conversion faite jusqu'ici à la main :

    <p><strong>TITRE</strong></p>        →  ### **TITRE**
    ⊱✦⊰──────⊱✦⊰   ou  <hr>             →  ---
    <br>                                 →  saut de ligne
    </p>                                 →  ligne vide
    <strong>x</strong>                   →  **x**
    <em>x</em>                           →  *x*
    <a href="u">t</a>                    →  [t](u)
    <img …>                              →  retiré
    <span>, <div>, styles               →  retirés, contenu conservé

Ce qui relève du choix éditorial — retirer un encart promotionnel, ajouter une
signature — n'est **pas** fait ici : c'est à l'auteur d'en décider.
"""

import html as _html
import re

# Lignes purement décoratives : ⊱✦⊰──────⊱✦⊰, ═════, ~~~~~, etc.
DECORATIVE = re.compile(
    r"^[\s\W_]*[─━═\-–—~⊱⊰✦✧★☆♦◆•·]{3,}[\s\W_]*$"
)


def _protect(text, pattern, store):
    """Met de côté un fragment déjà converti pour qu'il traverse la suite."""
    def keep(match):
        store.append(match.group(1))
        return f"\x00{len(store) - 1}\x00"
    return pattern.sub(keep, text)


def _restore(text, store):
    for index, value in enumerate(store):
        text = text.replace(f"\x00{index}\x00", value)
    return text


def _headings(text):
    """Un paragraphe entièrement en gras devient un titre de niveau 3.

    C'est la convention observée : les intertitres de Janitor (CONTEXTE,
    TRIGGER WARNINGS…) sont des `<p>` centrés ne contenant qu'un `<strong>`.
    """
    def clean(label):
        label = re.sub(r"<[^>]+>", "", label)
        return _html.unescape(label).replace("\xa0", " ").strip()

    seen = {"count": 0}

    def convert(match):
        inner = match.group(1)
        seen["count"] += 1
        first_paragraph = seen["count"] == 1
        # On enlève les enveloppes sans portée sémantique (span, font…).
        stripped = re.sub(r"</?(?:span|font|u)\b[^>]*>", "", inner).strip()

        # Le contenu du gras ne doit pas franchir sa propre balise fermante :
        # sans ce garde-fou, un paragraphe se terminant par du gras verrait le
        # premier `<strong>` s'étendre jusqu'au dernier `</strong>`.
        bold = r"<(strong|b)\b[^>]*>((?:(?!</(?:strong|b)\s*>).)*)</\1\s*>"

        # Cas 1 : un intitulé en gras, puis <br>, puis le corps du paragraphe.
        # C'est la forme des intertitres de Janitor (CONTEXTE, TRIGGER
        # WARNINGS…), où le texte suit immédiatement le titre.
        lead = re.match(bold + r"\s*<br\s*/?>(.*)", stripped, re.S | re.I)
        if lead:
            label = clean(lead.group(2))
            if label and len(label) <= 90:
                return f"\n\n### **{label}**\n\n{lead.group(3)}\n\n"

        # Cas 2 : le paragraphe n'est qu'un titre en gras.
        whole = re.fullmatch(bold, stripped, re.S | re.I)
        if whole:
            label = clean(whole.group(2))
            if label and len(label) <= 90:
                return f"\n\n### **{label}**\n\n"

        # Cas 3 : titre en gras **collé** au texte, sans saut de ligne —
        #   <p><strong>A PLACE TO CALL HOME</strong>Vous et Sukuna…</p>
        # Réservé au tout premier paragraphe : ailleurs, un simple
        # « <strong>TW :</strong> … » deviendrait un titre à tort.
        if first_paragraph:
            # Le texte doit commencer par un caractère de mot : `**Attention**!`
            # est une exclamation en gras, pas un titre suivi d'un paragraphe.
            glued = re.match(bold + r"\s*(\w.*)", stripped, re.S | re.I)
            if glued:
                label = clean(glued.group(2))
                if label and len(label) <= 90:
                    return f"\n\n### **{label}**\n\n{glued.group(3)}\n\n"

        return match.group(0)

    return re.sub(r"<p\b[^>]*>(.*?)</p\s*>", convert, text, flags=re.S | re.I)


def to_markdown(source):
    """Convertit le HTML de Janitor en Markdown."""
    if not isinstance(source, str) or "<" not in source:
        return (source or "").strip()

    text = source

    # Les images pointent vers le CDN de Janitor : on les retire plutôt que de
    # laisser des liens qui pourraient un jour ne plus répondre.
    # Les espaces insécables sont ramenés tôt à de vrais espaces : plus loin,
    # `.strip()` ne saurait pas les reconnaître et l'on obtiendrait un gras
    # bancal du genre `**TW: **`.
    text = text.replace("&nbsp;", " ").replace("\xa0", " ")

    text = re.sub(r"<img\b[^>]*>", "", text, flags=re.I)
    text = re.sub(r"<(script|style)\b.*?</\1\s*>", "", text, flags=re.S | re.I)

    text = _headings(text)

    # Liens : convertis tôt, puis mis à l'abri des nettoyages suivants.
    protected = []
    def link(match):
        # Les entités sont décodées ici : le lien est mis à l'abri juste après
        # et ne repasserait pas par le décodage général.
        label = _html.unescape(re.sub(r"<[^>]+>", "", match.group(2)))
        label = label.replace("\xa0", " ").strip()
        url = _html.unescape(match.group(1)).strip()
        return f"[{label}]({url})" if label else ""

    text = re.sub(
        r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a\s*>",
        link, text, flags=re.S | re.I,
    )
    text = _protect(text, re.compile(r"(\[[^\]]*\]\([^)]*\))"), protected)

    text = re.sub(r"<hr\b[^>]*/?>", "\n\n---\n\n", text, flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p\s*>|</div\s*>", "\n\n", text, flags=re.I)

    def emphasis(marker):
        """`**gras**` ne fonctionne pas si un espace jouxte les astérisques.

        On sort donc les espaces de bord des marqueurs, au lieu de les
        supprimer : `<strong>TW: </strong>Texte` doit rester « **TW:** Texte »
        et non « **TW:**Texte ».
        """
        def replace(match):
            inner = match.group(2)
            core = inner.strip()
            if not core:
                return " " if inner else ""
            before = " " if inner[:1].isspace() else ""
            after = " " if inner[-1:].isspace() else ""
            return f"{before}{marker}{core}{marker}{after}"
        return replace

    text = re.sub(r"<(strong|b)\b[^>]*>(.*?)</\1\s*>", emphasis("**"),
                  text, flags=re.S | re.I)
    text = re.sub(r"<(em|i)\b[^>]*>(.*?)</\1\s*>", emphasis("*"),
                  text, flags=re.S | re.I)

    text = re.sub(r"<[^>]+>", "", text)            # tout le reste part
    text = _html.unescape(text).replace("\xa0", " ")
    text = _restore(text, protected)

    # Séparateurs décoratifs → règle horizontale.
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        stripped = re.sub(r"\*\*(.*?)\*\*", r"\1", stripped).strip()
        lines.append("---" if stripped and DECORATIVE.fullmatch(stripped) else line)
    text = "\n".join(lines)

    # Gras strictement vide seulement. Une expression plus large (`\*\*\s*\*\*`)
    # souderait deux gras voisins séparés par un saut de ligne :
    # `**TITRE A**\n**TITRE B**` deviendrait `**TITRE ATITRE B**`.
    text = re.sub(r"\*\*\*\*", "", text)

    # Un gras collé au mot qui suit — `**Special Notes**27 ans` — vient du HTML
    # d'origine, où `</strong>` était immédiatement suivi du texte. On insère
    # l'espace manquant.
    #
    # Uniquement devant un caractère de mot : la ponctuation reste collée,
    # sinon `**Attention**!` deviendrait `**Attention** !`.
    text = re.sub(r"(\*\*[^*\n]+?\*\*)(?=\w)", r"\1 ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?:^|\n)---\n(?:\s*---\n)+", "\n---\n", text)

    return text.strip()


def to_plain_text(source):
    """Version sans balises ni Markdown, pour la description courte."""
    text = to_markdown(source)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*#>]+", "", text)
    return re.sub(r"[ \t]+", " ", text).strip()
