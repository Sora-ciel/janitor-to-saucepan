"""Rapprochement entre les bots Janitor et les companions déjà sur Saucepan.

Le registre ne connaît que ce que l'application a elle-même transféré. Les
companions créées à la main lui sont invisibles — et sans ce rapprochement,
elles seraient recopiées une seconde fois, en double.

    python -m naosnatcher.reconcile            # montre les correspondances
    python -m naosnatcher.reconcile --apply    # les inscrit au registre

Le rapprochement se fait sur le **titre** : `display_name` côté Saucepan
correspond au `name` côté Janitor (les deux sites nomment ces champs à
l'envers l'un de l'autre). La comparaison ignore la casse, les espaces
multiples et la ponctuation, car les titres saisis à la main varient —
« Ryomen Sukuna |  S2 » et « Ryomen Sukuna | S2 » désignent le même bot.
"""

import argparse
import json
import re
import sys

from . import state
from .driver import BrowserSession
from . import janitor

SEARCH_FRAGMENT = "/api/v1/search"
USER_PAGE = "https://saucepan.ai/user/{handle}"
ME_FRAGMENT = "/users/me"


def normalise(title):
    """Réduit un titre à sa forme comparable."""
    text = (title or "").lower()
    text = re.sub(r"\{\{.*?\}\}", "", text)      # variables de gabarit
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split()).strip()


def fetch_saucepan_companions(driver, log):
    """Companions visibles sur le profil public du compte connecté."""
    me = {}
    payloads = []

    def on_response(response):
        if response.status != 200 or "saucepan" not in response.url:
            return
        try:
            data = response.json()
        except Exception:                                          # noqa: BLE001
            return
        if ME_FRAGMENT in response.url and isinstance(data, dict) and data.get("handle"):
            me.update(data)
        elif SEARCH_FRAGMENT in response.url:
            payloads.append(data)

    driver.page.on("response", on_response)
    try:
        driver.goto("https://saucepan.ai/home")
        driver.page.wait_for_timeout(6000)
        handle = me.get("handle")
        if not handle:
            raise RuntimeError("Compte Saucepan non identifié (êtes-vous connecté ?).")

        log(f"Profil Saucepan : {handle}")
        driver.goto(USER_PAGE.format(handle=handle))
        driver.page.wait_for_timeout(7000)
        for _ in range(8):
            driver.eval_js(
                "() => { window.scrollTo(0, document.body.scrollHeight); return 1; }")
            driver.page.wait_for_timeout(1200)
    finally:
        driver.page.remove_listener("response", on_response)

    rows, total = {}, None
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        total = payload.get("total") or payload.get("total_count") or total
        for c in payload.get("companions") or []:
            if isinstance(c, dict) and c.get("id"):
                rows[c["id"]] = {
                    "id": c["id"],
                    "name": c.get("name"),
                    "display_name": c.get("display_name"),
                }

    if total and len(rows) < total:
        log(f"⚠ {len(rows)} companion(s) récupérées sur {total} annoncées.")
    return list(rows.values())


def match(janitor_bots, saucepan_companions):
    """Apparie les deux listes. Renvoie (couples, janitor_seuls, saucepan_seuls)."""
    index = {}
    for c in saucepan_companions:
        key = normalise(c.get("display_name"))
        if key:
            index.setdefault(key, []).append(c)

    pairs, unmatched_janitor = [], []
    used = set()
    for bot in janitor_bots:
        key = normalise(bot.get("name"))
        candidates = index.get(key)
        if candidates:
            companion = candidates[0]
            used.add(companion["id"])
            pairs.append((bot, companion))
        else:
            unmatched_janitor.append(bot)

    unmatched_saucepan = [c for c in saucepan_companions if c["id"] not in used]
    return pairs, unmatched_janitor, unmatched_saucepan


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m naosnatcher.reconcile",
        description="Marque comme déjà transférés les bots présents sur Saucepan.",
    )
    parser.add_argument("--apply", action="store_true",
                        help="inscrire les correspondances au registre")
    args = parser.parse_args(argv)

    settings = state.load_settings()
    log = lambda m: print("  ", m, flush=True)                     # noqa: E731

    with BrowserSession(log, settings.get("browser_path")) as driver:
        driver.page.set_viewport_size({"width": 1400, "height": 950})
        companions = fetch_saucepan_companions(driver, log)
        print(f"   {len(companions)} companion(s) sur Saucepan.")
        bots = janitor.list_characters(driver, settings["janitor_list_url"], log)

    pairs, _, orphans = match(bots, companions)

    print()
    print(f"=== {len(pairs)} CORRESPONDANCE(S) ===")
    for bot, companion in pairs:
        already = " (déjà au registre)" if state.is_seen(bot["id"]) else ""
        print(f"  {bot['name'][:56]:56}{already}")

    if orphans:
        print()
        print(f"=== {len(orphans)} COMPANION(S) SANS ÉQUIVALENT JANITOR ===")
        for c in orphans:
            print(f"  {str(c.get('display_name'))[:60]}")

    fresh = [(b, c) for b, c in pairs if not state.is_seen(b["id"])]
    print()
    if not args.apply:
        print(f"{len(fresh)} bot(s) seraient inscrits au registre. "
              "Ajoutez --apply pour appliquer.")
        return 0

    for bot, companion in fresh:
        state.mark_seen(
            bot["id"], name=bot.get("name"), status="ok",
            access_level="public" if bot.get("is_public") else "private",
            saucepan_url=f"https://saucepan.ai/companion/{companion['id']}",
            note="déjà présent sur Saucepan, rapproché par le titre",
        )
    print(f"{len(fresh)} bot(s) inscrits — ils ne seront pas transférés à nouveau.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
