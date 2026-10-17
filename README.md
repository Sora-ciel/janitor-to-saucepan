# Naosnatcher

Synchronisation automatique **Janitor AI ➜ Saucepan AI**.

Chaque jour à l'heure choisie, l'app regarde votre compte Janitor. Pour chaque
bot ajouté depuis la dernière fois, elle ouvre sa page d'édition, en extrait la
fiche, la convertit au format de backup Saucepan, la colle dans
**Restore Companion**, enregistre — et publie si le bot est public sur Janitor.

Elle fabrique aussi des **cartes de personnage** (PNG avec la fiche intégrée),
à partir d'un bot Janitor ou d'une fiche que vous remplissez vous-même.

## Télécharger

**[➜ Dernière version de Naosnatcher.exe](https://github.com/Sora-ciel/janitor-to-saucepan/releases/latest)**

Un seul fichier, pour Windows, sans Python à installer. Lancé, il propose de
s'installer (dans votre profil, sans droits administrateur) et demande où
ranger ses données.

L'exécutable n'est pas signé : au premier lancement, Windows SmartScreen
affiche « éditeur inconnu ». Cliquez **Informations complémentaires**, puis
**Exécuter quand même**.

Utilisation personnelle libre ; reprise ou redistribution du code interdite
sans autorisation — voir [LICENSE](LICENSE).

## Le navigateur est le vôtre

Naosnatcher **n'embarque pas** de navigateur. Il pilote le vôtre à distance.

C'est un choix imposé par Cloudflare : le contrôle « are you human » rejette les
navigateurs intégrés, et la case passe au rouge quoi qu'on fasse. Ce projet ne
contient aucun contournement de ce contrôle et n'en contiendra pas. Il le rend
inutile : **c'est vous qui vous connectez et qui passez le contrôle**, dans une
vraie fenêtre, en tant qu'humain. L'automatisation réutilise ensuite la session
qui en résulte.

Un profil dédié (`browser_state/cdp_profile`) est utilisé, pour ne pas exiger
que vous fermiez vos fenêtres en cours. Il démarre vierge : vous vous y
connectez une fois, la session y reste.

## Démarrage

Double-cliquez sur **`Launch Naosnatcher.bat`**. Au premier lancement il crée
l'environnement Python et installe les dépendances.

1. **Ouvrir le navigateur piloté** → connectez-vous à Janitor et à Saucepan.
2. Collez les deux adresses : votre liste de bots Janitor, et l'éditeur de
   nouvelle companion Saucepan.
3. **Marquer les bots actuels comme déjà connus.** Sans ça, la première
   synchronisation essaierait d'envoyer tout l'historique du compte d'un coup.
4. **Simulation** d'abord — elle va jusqu'au collage du JSON puis s'arrête,
   sans rien restaurer, enregistrer ni publier. C'est le moyen de tout vérifier
   sans risque.
5. Quand la simulation est propre, **Synchroniser maintenant**.

### Version installée (Windows)

Un seul fichier à distribuer : **`Naosnatcher.exe`**. Lancé depuis n'importe où,
il propose de s'installer — copie dans `%LOCALAPPDATA%\Programs\Naosnatcher`,
raccourcis menu Démarrer et bureau, entrée dans « Applications installées »
avec désinstallation, sans droits administrateur. Il s'ouvre ensuite sur son
**assistant de configuration** (navigateur, connexion aux deux sites, bots
existants, horaire), accessible plus tard depuis l'onglet Configuration.

Les données de la version installée vivent dans `%LOCALAPPDATA%\Naosnatcher`,
**pas** dans le dossier du projet. Si vous utilisiez déjà Naosnatcher depuis les
sources, cliquez « Importer une installation précédente » à la première page de
l'assistant et désignez ce dossier : sans cela, le registre repart de zéro.
Supprimez ensuite l'ancienne tâche du Planificateur qui lançait
`Sync quotidienne.bat` — deux tâches sur deux registres distincts enverraient
les mêmes bots deux fois.

Pour **construire** l'exécutable, sous Windows, comme pour KritraK :

```
python build.py
```

Les dépendances manquantes (PyInstaller compris) sont installées au passage.
Résultat : `dist\Naosnatcher.exe`. L'exécutable n'est pas signé : au premier
lancement, SmartScreen demande « Informations complémentaires » puis
« Exécuter quand même ».

### Sous Linux

Lancez **`./launch-naosnatcher.sh`** (équivalent du `.bat`) ; il crée son propre
environnement, `.venv-linux`, à côté de celui de Windows. `./sync-daily.sh` est
l'équivalent de `Sync quotidienne.bat`.

Le navigateur (Vivaldi, Chrome, Chromium…) est cherché dans le `PATH`. Son
profil dédié n'est pas partagé avec Windows — les cookies y sont chiffrés par
le système — : il faut donc s'y connecter une fois sous Linux. Il est rangé dans
`~/.local/share/naosnatcher/cdp_profile`, ou `~/snap/<nom>/common/naosnatcher-profile`
pour un navigateur installé en snap. Le registre, les réglages et le journal,
eux, restent communs aux deux systèmes.

## Organisation

```
naosnatcher/
  config.py       chemins, URLs par défaut, constantes
  state.py        bots déjà synchronisés, réglages, journal
  driver.py       raccordement au navigateur (Playwright/CDP) + aides JS
  janitor.py      liste des bots et lecture d'une fiche
  htmlmd.py       HTML de Janitor  ➜  Markdown
  housestyle.py   mise en forme maison (sections, signature, avertissements)
  convert.py      Janitor  ➜  format Saucepan, avec validation locale
  avatar.py       récupération de l'avatar et dépôt dans le formulaire
  saucepan.py     collage du backup, enregistrement, publication
  sync.py         enchaînement complet
  card.py         cartes de personnage (PNG + fiche intégrée)
  schedule.py     tâche planifiée du système (Windows / systemd)
  wizard.py       assistant de configuration
  launcher.py     point d'entrée (fenêtre, --sync, --uninstall)
  install.py      auto-installation de Naosnatcher.exe (sur le modèle de KritraK)
  app.py          fenêtre, planification

data/           état local et réglages
  saucepan_tags.json   les 540 tags acceptés (nécessaire à l'exécution)
  housestyle.json      vos choix de mise en forme — modifiable à la main
  seen_bots.json       bots déjà synchronisés
  settings.json        URLs, heure de la synchronisation
  sync.log             journal
  avatars/             avatars mis en cache

exports/        un JSON par bot traité, pour vérifier ou rejouer à la main
browser_state/  profil du navigateur piloté (ne pas partager)
```

## Cartes de personnage

Onglet **Cartes de personnage** : l'avatar d'un bot en PNG, avec sa fiche
complète intégrée (blocs `chara` v2 et `ccv3` v3) — le format que Janitor,
SillyTavern ou Chub savent importer. Deux sources :

- **une adresse Janitor**, celle de n'importe quel bot. Si son créateur a masqué
  la définition, la carte ne porte que le nom, la présentation et l'avatar ;
- **vos bots synchronisés**, à cocher dans la liste.

La case « Créer automatiquement… » ajoute la carte à chaque synchronisation.
Les fichiers vont dans `cards/`.

Onglet **Créer une carte** : votre propre image et votre propre fiche — titre,
nom en conversation, personnalité, scénario, premiers messages, exemples,
présentation, tags. « Ouvrir une carte existante » la recharge pour la
retoucher ; les cartes SillyTavern sont reprises avec la définition à sa place.

Correspondances, calquées sur l'**importeur de Janitor** (relevé en déposant
une carte sur l'avatar d'un nouveau bot) : `personality` de Janitor →
`personality` de la carte (case « Personality »), présentation en HTML
d'origine → `description` (affichée fidèlement par l'éditeur riche de
Janitor), copie Markdown → `creator_notes`, premiers messages supplémentaires
→ `alternate_greetings`. C'est l'inverse de la convention SillyTavern.

## Les noms, et pourquoi ils sont inversés

Les deux sites emploient les mêmes mots dans un sens opposé :

| | Janitor | Saucepan |
|---|---|---|
| titre complet | `name` | `display_name` |
| nom court, celui de la conversation | `chat_name` | `name` |

La conversion les échange donc. Si Janitor ne donne pas de nom court, il est
déduit du titre en gardant le premier segment : « Ryomen Sukuna | The Butcher »
donne « Ryomen Sukuna ».

## L'aperçu, et sa limite de 140 caractères

L'aperçu affiché dans les listes est le **premier paragraphe qui suit le
titre**. S'il dépasse les 140 caractères autorisés par Saucepan, il n'est pas
tronqué — un aperçu coupé au milieu d'une phrase se lit mal : c'est le titre
qui sert alors d'aperçu, et le cas est noté.

Pour savoir quels bots mériteraient un résumé écrit à la main :

```bash
python -m naosnatcher.notify
```

Et pour recevoir la liste par courriel :

```bash
python -m naosnatcher.notify --send
```

Les réglages d'envoi vont dans `data/settings.json`, sous une clé `mail`
(`smtp_host`, `smtp_port`, `username`, `from`, `to`). Le mot de passe, lui,
n'est jamais écrit sur le disque : il est lu dans la variable d'environnement
`NAOSNATCHER_SMTP_PASSWORD`.

## Réglages appliqués à chaque companion

Quatre réglages sont posés automatiquement, via le JSON plutôt qu'en cliquant
dans l'éditeur — ce qui épargne quelques centaines d'interactions sur
l'ensemble d'un compte :

| Réglage | Valeur |
|---|---|
| Definition Visibility | Open (`open_definition`, `hidden_fields: 0`) |
| Lock Starting Message | activé |
| External Model Access | Vetted only |

Vérifié en direct : après « Restore Data », le brouillon porte bien ces
valeurs. Modifiables dans `data/settings.json`, clé `companion_defaults`.

## Cadence et filtres

| Réglage | Défaut | Effet |
|---|---|---|
| `min_tokens` | 500 | écarte sondages, annonces et brouillons |
| `public_only` | `true` | ne transfère que les bots publics sur Janitor |
| `daily_limit` | 2 | bots envoyés par exécution |
| `pause_between_bots` | 20 | secondes entre deux bots |

Le reste de la file repart au passage suivant.

## Rapprochement avec l'existant

Le registre ne connaît que ce que l'application a transféré. Pour les
companions créées à la main :

```bash
python -m naosnatcher.reconcile
```

Il rapproche les titres des deux côtés et montre ce qu'il trouve ; `--apply`
inscrit les correspondances au registre pour éviter les doublons.

## Régler la mise en forme

`data/housestyle.json` contient les choix éditoriaux appliqués à chaque
description : sections supprimées, signature de fin, décoration des
avertissements, lignes écartées. Le modifier suffit — aucun code à toucher.

## Le format Saucepan

Il est connu **exactement** : en collant un premier export, le site a répondu
par la liste complète de ses règles de validation. Enseignement central,
Saucepan valide contre pratiquement le même schéma que Janitor — la conversion
est donc un passage direct des champs, pas une traduction.

`convert.validate()` rejoue ces règles **en local**, avant d'ouvrir quoi que ce
soit : les 540 tags autorisés, les booléens `sus`/`very_sus`, l'énumération
`access_level`, `example_dialogue` en chaîne, la présence d'une image. Une
erreur de format se voit donc immédiatement, sans aller-retour dans le
navigateur.

Détail complet dans **`SCHEMA_NOTES.md`**.

## Prudence intégrée

- **Mode simulation** : tout le parcours sauf les trois gestes irréversibles.
- **Publication conservatrice** : tout ce qui n'est pas explicitement
  `access_level: "public"` côté Janitor reste privé sur Saucepan.
- **Liste restreinte** : seuls les bots de la grille principale sont retenus.
  Les carrousels de suggestions sont écartés — sans quoi, en mode automatique,
  les bots d'autres gens seraient recopiés puis publiés sur votre compte. Le
  formulaire d'édition sert en plus de vérification d'appartenance.
- **Échec isolé** : un bot en erreur n'interrompt pas les suivants, reste hors
  du registre et sera **retenté** au cycle suivant.
- **Rattrapage** : PC éteint à l'heure prévue → la synchronisation part au
  démarrage suivant plutôt que de sauter la journée.
- Chaque JSON est écrit dans `exports/` avant l'envoi.

## Repérage des éléments

Les boutons sont trouvés **par leur libellé visible**, jamais par leur classe :
Saucepan utilise des classes générées (`sc-dTvVRJ`, `hNtzVn`…) qui changent à
chaque déploiement, alors que « Restore Data » reste « Restore Data ».

Pour écrire dans les champs React, `driver.py` passe par le setter natif du
prototype puis émet un `input` bouillonnant — une affectation directe de
`.value` serait ignorée par React et le bouton resterait désactivé.

## Ce qui reste ouvert

- **L'avatar.** Saucepan exige une image de profil ; Janitor n'en donne qu'un
  identifiant valable sur son propre CDN. On le transmet tel quel — reste à
  vérifier si Saucepan l'accepte. Sinon, il faudra téléverser l'image d'abord.
- **Les libellés des boutons Enregistrer et Publier**, inconnus : la capture
  disponible ne couvre que l'onglet Réglages. Candidats dans
  `saucepan.SAVE_LABELS` et `saucepan.PUBLISH_LABELS`.
