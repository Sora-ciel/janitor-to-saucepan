"""Lecture des bots depuis Janitor AI, dans le navigateur de l'utilisateur."""

from . import config
from .driver import DriverError

# ── Repérage des bots du compte ─────────────────────────────────────────────
#
# Prudence délibérée : une page Janitor affiche aussi des bots *recommandés*
# (carrousels, barres latérales, pied de page). Les ramasser reviendrait à
# recopier les bots d'autres gens sur votre compte Saucepan — et, en mode
# automatique, à les publier. On restreint donc la recherche au conteneur de
# liste principal, et on vérifie ensuite que chaque fiche est bien modifiable
# par vous (présence d'un lien ou d'un bouton d'édition).

JS_LIST_CHARACTERS = r"""
() => {
  const RE = /\/characters\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i;

  // On cherche le plus petit conteneur qui rassemble le gros des liens de
  // personnages : c'est la grille principale, pas un carrousel de suggestions.
  const links = [...document.querySelectorAll('a[href*="/characters/"]')]
    .filter(a => RE.test(a.getAttribute('href') || ''));
  if (!links.length) return { scoped: false, items: [] };

  const score = new Map();
  for (const a of links) {
    let node = a.parentElement;
    for (let depth = 0; node && depth < 6; depth++, node = node.parentElement) {
      score.set(node, (score.get(node) || 0) + 1);
    }
  }
  let container = null, best = 0;
  for (const [node, n] of score) {
    // À nombre de liens égal, on garde le conteneur le plus profond (le plus
    // petit), ce qui exclut <body> et les grandes enveloppes de page.
    if (n > best || (n === best && container && container.contains(node))) {
      best = n; container = node;
    }
  }

  const scope = container || document;
  const found = new Map();
  for (const a of scope.querySelectorAll('a[href*="/characters/"]')) {
    const m = (a.getAttribute('href') || '').match(RE);
    if (!m) continue;
    const raw = (a.innerText || a.textContent || '');

    // Le libellé du lien contient aussi des compteurs (« 2 tokens », nombre
    // de discussions…). On écarte ces lignes purement numériques pour ne pas
    // afficher « 2 tokens » à la place du nom du bot.
    const lines = raw.split('\n').map(s => s.trim())
      .filter(s => s && !/^[\d\s.,kKmM]+(tokens?|chats?|messages?|likes?)?$/i.test(s));
    const label = lines[0] || '';

    // Le nombre de jetons figure sur la carte : « 1.7k tokens ». Le relever
    // ici évite d'ouvrir les 200 fiches du compte pour écarter les annonces
    // et les sondages, qui n'en comptent qu'une poignée.
    let tokens = null;
    const tk = raw.match(/([\d.,]+)\s*([kKmM])?\s*tokens?/);
    if (tk) {
      let value = parseFloat(tk[1].replace(/,/g, ''));
      const unit = (tk[2] || '').toLowerCase();
      if (unit === 'k') value *= 1000;
      else if (unit === 'm') value *= 1000000;
      if (!Number.isNaN(value)) tokens = Math.round(value);
    }

    const previous = found.get(m[1]);
    if (!previous) {
      found.set(m[1], { id: m[1], name: label, tokens: tokens });
    } else {
      if (label && !previous.name) previous.name = label;
      if (tokens != null && previous.tokens == null) previous.tokens = tokens;
    }
  }
  return {
    scoped: !!container,
    total_on_page: new Set(links.map(a => a.getAttribute('href').match(RE)[1])).size,
    items: [...found.values()],
  };
}
"""

JS_SCROLL_BOTTOM = "() => { window.scrollTo(0, document.body.scrollHeight); return true; }"

# ── Pagination ──────────────────────────────────────────────────────────────
#
# La liste « mes personnages » est **paginée**, pas à défilement infini : sans
# parcourir les pages, on ne voit qu'un tiers du compte. Les boutons ne portent
# ni lien ni libellé exploitable — juste un numéro — et sont alignés sur une
# même rangée en bas de page. On retient donc le groupe de boutons numériques
# partageant la même ordonnée : c'est la pagination, et non un compteur isolé
# tombé au milieu d'une carte.
JS_MARK_PAGES = r"""
() => {
  const candidates = [];
  for (const el of document.querySelectorAll('button, a, [role="button"]')) {
    const t = (el.innerText || '').trim();
    if (!/^\d{1,3}$/.test(t)) continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    candidates.push({ el: el, page: parseInt(t, 10), y: Math.round(r.top) });
  }
  if (!candidates.length) return { pages: [] };

  const rows = new Map();
  for (const c of candidates) {
    if (!rows.has(c.y)) rows.set(c.y, []);
    rows.get(c.y).push(c);
  }
  let best = [];
  for (const group of rows.values()) {
    if (group.length > best.length) best = group;
  }
  if (best.length < 2) return { pages: [] };

  document.querySelectorAll('[data-naos-page]')
    .forEach(e => e.removeAttribute('data-naos-page'));
  for (const c of best) c.el.setAttribute('data-naos-page', String(c.page));

  return { pages: best.map(c => c.page).sort((a, b) => a - b) };
}
"""

JS_COUNT = r"""
() => new Set([...document.querySelectorAll('a[href*="/characters/"]')]
  .map(a => (a.getAttribute('href') || '').match(/\/characters\/([0-9a-f-]{36})/i))
  .filter(Boolean).map(m => m[1])).size
"""

# Fragment d'URL de l'appel que la page d'édition passe à l'API de Janitor.
# On intercepte sa réponse plutôt que de refaire la requête nous-mêmes : elle
# porte un jeton `Bearer` que seule la page détient. Voir goto_capturing().
API_CHARACTER_FRAGMENT = "/hampter/characters/"

JS_SCRAPE_EDIT_FORM = r"""
() => {
  const val = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    return el.type === 'checkbox' ? el.checked : el.value;
  };
  const firsts = [];
  document.querySelectorAll('[name^="first_messages."]').forEach((el) => {
    const i = parseInt(el.name.split('.')[1], 10);
    if (!Number.isNaN(i)) firsts[i] = el.value;
  });
  return { source: 'dom', data: {
    name:            val('[name="name"]'),
    chat_name:       val('[name="chat_name"]'),
    personality:     val('[name="personality"]'),
    scenario:        val('[name="scenario"]'),
    example_dialogs: val('[name="example_dialogs"]'),
    first_messages:  firsts.filter(x => x != null),
    is_nsfw:         val('[name="is_nsfw"]'),
  }};
}
"""

# Le formulaire d'édition n'est servi que pour les bots dont vous êtes
# propriétaire : sa présence vaut donc vérification d'appartenance.
JS_CAN_EDIT = """
() => !!document.querySelector('[name="name"]') ||
      !!document.querySelector('[name="personality"]')
"""


# La page « mes personnages » se nourrit d'un appel qui renvoie tout ce dont on
# a besoin — identifiant, nom, visibilité, nombre de jetons — et annonce le
# total. L'intercepter vaut infiniment mieux que de lire les cartes : plus de
# devinette sur le conteneur, plus d'analyse du texte « 1.7k tokens », et
# surtout `is_public`, que le DOM n'expose pas.
API_LIST_FRAGMENT = "/hampter/characters/v2/mine"


def _rows_from_payload(payload):
    """Transforme une réponse de l'API en [{id, name, is_public, tokens}]."""
    rows = []
    for item in (payload or {}).get("data") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        rows.append({
            "id": str(item["id"]),
            "name": (item.get("name") or "").strip(),
            "is_public": item.get("is_public"),
            "tokens": item.get("total_tokens"),
            # Dates conservées pour pouvoir trier explicitement, plutôt que de
            # se fier à l'ordre de la réponse.
            "created_at": item.get("created_at") or "",
            "updated_at": item.get("updated_at") or "",
        })
    return rows


def list_characters(driver, list_url, log, scroll_rounds=12):
    """Liste les bots du compte.

    Renvoie [{id, name, is_public, tokens}, …]. On passe par l'API que la page
    interroge elle-même ; à défaut seulement, on retombe sur la lecture des
    cartes, qui ne donne ni visibilité ni total fiable.
    """
    payloads = []

    def on_response(response):
        if API_LIST_FRAGMENT in response.url and response.status == 200:
            try:
                payloads.append(response.json())
            except Exception:                                      # noqa: BLE001
                pass

    driver.page.on("response", on_response)
    try:
        return _list_via_api(driver, list_url, log, payloads, scroll_rounds)
    finally:
        driver.page.remove_listener("response", on_response)


def _wait_payload(driver, payloads, count_before, timeout=15_000):
    waited = 0
    while len(payloads) <= count_before and waited < timeout:
        driver.page.wait_for_timeout(250)
        waited += 250
    return len(payloads) > count_before


def _list_via_api(driver, list_url, log, payloads, scroll_rounds):
    log(f"Ouverture de la liste Janitor : {list_url}")
    driver.goto(list_url)

    if driver.is_logged_out():
        raise DriverError(
            "Session Janitor expirée. Connectez-vous dans la fenêtre du "
            "navigateur, puis relancez la synchronisation."
        )

    _wait_payload(driver, payloads, 0, timeout=25_000)

    if not payloads:
        log("⚠ Appel de liste non intercepté — lecture des cartes. "
            "La visibilité des bots sera inconnue.")
        return _list_via_dom(driver, log, scroll_rounds)

    found = {}
    for row in _rows_from_payload(payloads[0]):
        found[row["id"]] = row

    total = payloads[0].get("total")
    size = payloads[0].get("size") or len(found) or 1
    expected_pages = -(-total // size) if total else 1

    if expected_pages > 1:
        log(f"{total} bot(s) annoncés — {expected_pages} page(s) à parcourir.")

    pages = (driver.eval_js(JS_MARK_PAGES) or {}).get("pages") or []
    remaining = sorted(p for p in pages if p > 1)
    visited = {1}

    while remaining:
        page = remaining.pop(0)
        if page in visited:
            continue
        before = len(payloads)
        try:
            driver.page.click(f'[data-naos-page="{page}"]', timeout=10_000)
        except Exception:                                          # noqa: BLE001
            log(f"⚠ Page {page} inaccessible — ignorée.")
            visited.add(page)
            continue

        visited.add(page)
        if _wait_payload(driver, payloads, before):
            for row in _rows_from_payload(payloads[-1]):
                found.setdefault(row["id"], row)
        else:
            log(f"⚠ Page {page} : aucune réponse d'API reçue.")

        driver.install_helpers()
        pages = (driver.eval_js(JS_MARK_PAGES) or {}).get("pages") or []
        for p in pages:
            if p not in visited and p not in remaining:
                remaining.append(p)
        remaining.sort()

    items = list(found.values())

    if total and len(items) < total:
        # Mieux vaut le dire que de laisser croire le compte complet : c'est
        # exactement ce qui avait masqué six pages sur sept.
        log(f"⚠ {len(items)} bot(s) récupérés sur {total} annoncés — "
            "certaines pages n'ont pas répondu.")

    log(f"{len(items)} bot(s) dans votre liste.")
    return items


def _list_via_dom(driver, log, scroll_rounds=12):
    """Repli : lecture des cartes de la page déjà ouverte.

    Ne donne ni la visibilité ni un nombre de jetons garanti : à n'utiliser
    que si l'API n'a pas répondu.
    """
    driver.wait_for("document.querySelectorAll('a[href*=\"/characters/\"]').length > 0")

    found = {}
    unscoped_warned = False

    def harvest():
        """Ramasse les bots de la page affichée."""
        nonlocal unscoped_warned
        previous = -1
        for _ in range(scroll_rounds):
            count = driver.eval_js(JS_COUNT)
            if count == previous:
                break
            previous = count
            driver.eval_js(JS_SCROLL_BOTTOM)
            driver.page.wait_for_timeout(900)

        result = driver.eval_js(JS_LIST_CHARACTERS)
        if not result.get("scoped") and not unscoped_warned:
            unscoped_warned = True
            log("⚠ Conteneur de liste non identifié — tous les liens de la "
                "page ont été retenus. Vérifiez le résultat avant de laisser "
                "tourner en automatique.")
        for item in result.get("items", []):
            existing = found.get(item["id"])
            if not existing:
                found[item["id"]] = item
                continue
            if item.get("name") and not existing.get("name"):
                existing["name"] = item["name"]
            if item.get("tokens") is not None and existing.get("tokens") is None:
                existing["tokens"] = item["tokens"]
        return len(result.get("items", []))

    harvest()

    pages = (driver.eval_js(JS_MARK_PAGES) or {}).get("pages") or []
    remaining = [p for p in pages if p > 1]

    if remaining:
        log(f"Liste paginée : {max(pages)} page(s) à parcourir.")

    visited = {1}
    while remaining:
        page = remaining.pop(0)
        if page in visited:
            continue
        try:
            driver.page.click(f'[data-naos-page="{page}"]', timeout=10_000)
        except Exception:                                          # noqa: BLE001
            log(f"⚠ Page {page} inaccessible — ignorée.")
            visited.add(page)
            continue

        driver.page.wait_for_timeout(1800)
        driver.install_helpers()
        visited.add(page)
        on_page = harvest()
        log(f"  page {page} : {on_page} bot(s), {len(found)} au total.")

        # La pagination n'affiche qu'une fenêtre de numéros : de nouvelles
        # pages peuvent apparaître au fur et à mesure qu'on avance.
        pages = (driver.eval_js(JS_MARK_PAGES) or {}).get("pages") or []
        for p in pages:
            if p not in visited and p not in remaining:
                remaining.append(p)
        remaining.sort()

    items = list(found.values())
    log(f"{len(items)} bot(s) dans votre liste.")
    return items


def fetch_character(driver, char_id, edit_url_template, log):
    """Renvoie la fiche complète d'un bot, au format natif Janitor."""
    # On ouvre la page d'édition en écoutant l'appel qu'elle passe à l'API :
    # sa réponse est le JSON natif complet, avec access_level, image et tags —
    # que le formulaire, lui, n'expose pas.
    data = driver.goto_capturing(
        edit_url_template.format(char_id=char_id), API_CHARACTER_FRAGMENT)
    source = "api"

    # Page React : le formulaire se monte après la récupération de la fiche.
    try:
        driver.wait_for(
            'document.querySelector(\'[name="name"]\') '
            '|| document.querySelector(\'[name="personality"]\')',
            timeout=40_000,
        )
    except Exception as exc:                                       # noqa: BLE001
        raise DriverError(
            f"Aucun formulaire d'édition pour {char_id} après 40 s — soit ce "
            "bot ne vous appartient pas, soit la page n'a pas fini de charger."
        ) from exc

    if not data or not data.get("name"):
        log("⚠ Réponse d'API non interceptée — lecture du formulaire. "
            "access_level, image et tags seront absents.")
        data = (driver.eval_js(JS_SCRAPE_EDIT_FORM) or {}).get("data") or {}
        source = "formulaire"

    if not data.get("name"):
        raise DriverError(f"Fiche {char_id} vide ou illisible.")

    data.setdefault("id", str(char_id))
    log(f"Fiche lue « {data.get('name')} » (source : {source})")
    return data


def fetch_any_character(driver, char_id, edit_url_template, log):
    """Fiche d'un bot quelconque — le vôtre ou celui de quelqu'un d'autre.

    On lit d'abord la page publique du bot. Si la définition y est masquée
    (créateur ayant caché ses champs), on tente la page d'édition, qui ne
    s'ouvre que pour vos propres bots.
    """
    data = driver.goto_capturing(
        config.JANITOR_VIEW_URL.format(char_id=char_id),
        API_CHARACTER_FRAGMENT + char_id,
        accept=lambda d: isinstance(d, dict) and str(d.get("id")) == char_id,
    )
    if data and data.get("personality"):
        data.setdefault("id", char_id)
        log(f"Fiche lue « {data.get('name')} » (page publique)")
        return data

    try:
        return fetch_character(driver, char_id, edit_url_template, log)
    except DriverError:
        if data and data.get("name"):
            log("⚠ Définition masquée par son créateur — la carte ne portera "
                "que le nom, la présentation et l'avatar.")
            data.setdefault("id", char_id)
            return data
        raise DriverError(
            f"Impossible de lire le bot {char_id} : page introuvable, ou "
            "session Janitor expirée."
        )
