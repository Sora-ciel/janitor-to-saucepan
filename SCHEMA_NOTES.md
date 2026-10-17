# Notes de schéma — Janitor ➜ Saucepan

Tout ce qui suit a été relevé sur des données réelles : captures de pages,
réponses d'API interceptées, messages d'erreur du site.

## Sources

| Fichier | Ce qu'il prouve |
|---|---|
| `data/janitor_api_sample.json` | La réponse de l'API Janitor, interceptée sur le compte. |
| `Sukuna ... after edit button press.html` | Le formulaire d'édition Janitor et sa table de routage. |
| `Json from Sukuna ... .json` | Une fiche au format **Saucepan** (voir ci-dessous). |
| `Companion Editor sacuepanai.html` | L'onglet Réglages de Saucepan, section Backup/Restore. |
| `Companion Editor when i put our naosnatcher export.html` | **Les règles de validation de Saucepan**, obtenues en collant un export refusé. |
| `saucepan profile with image area.html` | Les champs d'image. |
| `publish html.html` | La visibilité et le bouton d'enregistrement. |

## Deux vocabulaires distincts

Le fichier `Json from Sukuna ... .json` n'est **pas** au format de l'API
Janitor, contrairement à ce qu'on a d'abord supposé. Ses champs (`card`,
`starting_scenarios`, `access_level`, `sus`, `companion_profile_banner_*`) sont
ceux que le validateur de Saucepan réclame : c'est une fiche **Saucepan**.

Le vrai format Janitor vient de `/hampter/characters/:id` :

| Janitor (API) | Saucepan |
|---|---|
| `personality` | `card` |
| `description` | `full_description` (+ `short_description` dérivée) |
| `example_dialogs` | `example_dialogue` |
| `first_messages[]` (chaînes) | `starting_scenarios[{title, message, portrait_id}]` |
| `is_public` (booléen) | `access_level` (énumération) |
| `is_nsfw` | `sus` |
| `tags[]` + `custom_tags[]` | `tags[]` (énumération de 540 valeurs) |
| `avatar` (nom de fichier) | `image` (**téléversement requis**) |

C'est donc une traduction champ par champ. La première version de `convert.py`
supposait un passage direct : elle traduisait en réalité du Saucepan vers du
Saucepan.

**Authentification.** L'API exige un en-tête `Bearer` que seule la page
détient. Plutôt que d'extraire et rejouer ce jeton, `driver.goto_capturing()`
laisse la page faire sa propre requête authentifiée et lit sa réponse au
passage — procédé qui survit à un changement de mécanisme d'authentification.

**Routes Janitor**, relevées dans la table de routage du site :
`/my_characters`, `/characters/:characterId`, `/edit_character/:characterId`.

**Avatars** : `https://ella.janitorai.com/bot-avatars/<nom>.webp`, avec un
paramètre `?width=N` facultatif. Sans lui, on obtient l'original.

## Les règles de validation de Saucepan

En collant un premier export, le site a répondu par la liste complète de ses
règles :

| Règle | Traitement |
|---|---|
| `sus` booléen obligatoire | dérivé de `is_nsfw` |
| `very_sus` booléen obligatoire | défaut `False` |
| `image` obligatoire | avatar déposé **avant** le collage, puis repris du backup Saucepan |
| `tags[]` dans une énumération de 540 valeurs | `collect_tags()` filtre et normalise |
| `example_dialogue` chaîne obligatoire | défaut `""` |
| `access_level` énumération | `public` seulement si `is_public` est vrai |

L'énumération complète est dans `data/saucepan_tags.json`.
`convert.validate()` rejoue ces règles **en local**, ce qui évite un
aller-retour dans le navigateur pour une erreur visible tout de suite.

## L'éditeur est multi-pages

| Page | Ce qu'elle porte |
|---|---|
| `/editor/new/settings` | Backup/Restore Companion — le collage du JSON |
| `/editor/new/profile` | avatar et bannière |
| `/editor/new/publish` | visibilité + enregistrement |

**Champs d'image** :

    <input id="profile-image"             accept="image/png,image/jpg,image/jpeg,image/gif,image/webp">
    <input id="companion-profile-banner"  accept="… mêmes types …">

Les deux acceptent exactement les mêmes types : un sélecteur générique
`input[type="file"][accept*="image"]` risquerait de déposer l'avatar dans la
bannière — companion sans photo de profil, et aucune erreur pour le signaler.
On cible donc `#profile-image`, et le repli écarte tout identifiant contenant
« banner ». Vérifié : le fichier atterrit dans l'avatar, la bannière reste vide.

**Visibilité** : trois boutons dont les libellés reprennent exactement
l'énumération — `Private`, `Unlisted`, `Public`. On recopie le niveau de
Janitor plutôt que de basculer un booléen.

**Enregistrement** : le bouton en bas à gauche s'appelle **`Create`** pour une
nouvelle companion (pleine largeur, 72 px), et non « Save ». Il reste
**désactivé** tant que la fiche est incomplète — un `Create` grisé n'est donc
pas un bouton manquant. `save()` distingue les deux cas et joint les
« Validation errors » si le site en affiche.

Les pages affichent « Draft saved », mais cela ne vaut que pour la navigation
interne : un rechargement par URL emporte bel et bien le brouillon. Voir la
section suivante.

## HTML de Janitor → Markdown de Saucepan

Seul le champ `description` de Janitor contient du HTML enrichi ; `personality`
et `first_messages` sont en texte brut (vérifié sur une fiche réelle).
Saucepan, lui, affiche du Markdown : recopier le HTML donnerait une fiche
pleine de balises. `htmlmd.py` fait la conversion :

    <p><strong>TITRE</strong></p>        →  ### **TITRE**
    <p><strong>TITRE</strong><br>texte</p>  →  ### **TITRE** + texte
    ⊱✦⊰──────⊱✦⊰   ou  <hr>             →  ---
    <br> / </p>                          →  saut de ligne / ligne vide
    <strong> / <em>                      →  ** / *
    <a href="u">t</a>                    →  [t](u)
    <img …>                              →  retiré
    <span>, <div>, styles               →  retirés, contenu conservé

Trois pièges rencontrés, tous silencieux :

- **`fullmatch` avec un quantificateur paresseux s'étend quand même.** Le test
  « ce paragraphe n'est-il qu'un titre ? » capturait jusqu'au *dernier*
  `</strong>` du paragraphe ; tout paragraphe finissant en gras échouait donc à
  devenir un titre. Le motif tempère désormais le contenu du gras.
- **`\*\*\s*\*\*` soude deux gras voisins.** `**A**\n**B**` devenait `**AB**`.
  On ne supprime plus que `****`, strictement vide.
- **Les espaces doivent rester hors des astérisques.** `<strong>TW: </strong>`
  donnait `**TW:**Texte` sans espace ; les `&nbsp;` sont ramenés à de vrais
  espaces avant tout traitement.

Ce qui relève du **choix éditorial** n'est pas automatisé : retirer un encart
promotionnel, ajouter une signature, réécrire un lien. C'est à l'auteur d'en
décider.

## La barre latérale, et pourquoi elle est indispensable

L'éditeur se parcourt par une colonne d'icônes de 60 px collée à gauche. Ce
sont des `<div>` sans libellé ni URL : la navigation est gérée par React, et
c'est **elle seule** qui préserve le brouillon. Changer de page par l'URL
recharge l'application et emporte tout ce qui n'est pas enregistré — y compris
l'avatar qu'on vient de déposer.

Les tuiles n'ayant ni texte ni `href`, on ne peut pas deviner laquelle mène où.
`go_to_editor_page()` clique, lit l'adresse obtenue et retient la
correspondance pour la session. Aucun ordre n'est supposé, et un réagencement
du site se corrige de lui-même. Carte relevée à l'exécution :

    publish 0 · core 1 · profile 2 · messages 3
    expressions 4 · lorebooks 5 · preview 6 · settings 7

Le repérage est **géométrique** (colonne à gauche, ~60×52, contient un `svg`) :
les classes (`sc-cnLhvP`…) sont générées et changent à chaque déploiement.

## Ce qui active « Restore Data »

Le bouton reste grisé tant que le JSON ne passe pas **toute** la validation.
Le site l'affiche alors sous « Validation errors » :

    short_description: Short description is required
    full_description:  Full description is required
    image:             Profile image is required
    tags:              At least one tag is required

Conséquence majeure : **l'image doit être dans le JSON**, et son identifiant
n'existe qu'après un dépôt. D'où l'ordre retenu — déposer l'avatar, demander à
Saucepan son propre backup (qui porte alors l'image), y superposer nos champs,
puis coller.

La zone de collage est un **basculeur** : « Backup Companion » l'affiche en
lecture seule, « Restore Companion » la rend inscriptible. Il faut donc
repasser en mode restauration après avoir lu le backup.

Deux replis sont nécessaires, faute de quoi beaucoup de bots seraient refusés :
descriptions vides → on retombe sur la définition puis le nom ; aucun tag →
`unknown`, qui appartient à l'énumération et signifie « non catégorisé ».

## L'ordre des opérations, et pourquoi

L'avatar doit être déposé **avant** le collage, puisque le JSON ne peut passer
la validation sans lui et que son identifiant n'existe qu'après le dépôt :

1. barre latérale → `profile`, dépôt de l'avatar dans `#profile-image` ;
2. barre latérale → `settings`, « Backup Companion » : Saucepan produit son
   propre backup, qui porte désormais l'image ;
3. « Restore Companion » pour rendre la zone inscriptible ;
4. fusion de nos champs traduits sur ce backup — tout ce qu'on ne traduit pas
   (recadrages, `hidden_fields`, bannière) reste tel que Saucepan l'a écrit ;
5. collage, « Restore Data » ;
6. barre latérale → `publish`, visibilité, puis `Create`.

Le marqueur interne `pending_upload` ne sert qu'à la validation locale : il est
remis à `null` avant le collage, et `merge_onto_base()` veille à ce qu'il
n'écrase jamais l'image venue du backup.

## Vérifié en direct

Le parcours complet a été exécuté en simulation contre le site réel : avatar
déposé, backup récupéré, fusion, collage — et « Restore Data » **actif, sans
aucune erreur de validation**. Restent à éprouver en direct les trois gestes
irréversibles : Restore Data, la visibilité et « Create ».

## Cloudflare

Le contrôle « are you human » échoue dans un navigateur intégré (QtWebEngine) :
la case passe au rouge. Ce n'est pas un réglage à trouver — Cloudflare rejette
l'environnement lui-même.

**Aucun contournement ne sera écrit dans ce projet.** L'architecture retenue
fait passer le contrôle par un humain, dans son propre navigateur, et
l'automatisation se contente d'utiliser la session ainsi obtenue.
