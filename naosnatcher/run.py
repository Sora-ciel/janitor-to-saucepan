"""Une synchronisation, sans interface.

Pensé pour le Planificateur de tâches de Windows : la fenêtre n'a pas besoin
d'être ouverte, ni même une session interactive côté application. Le navigateur
piloté, lui, reste nécessaire — c'est lui qui porte vos sessions Janitor et
Saucepan — et il est démarré automatiquement s'il ne tourne pas déjà.

    python -m naosnatcher.run              # un cycle, selon les réglages
    python -m naosnatcher.run --dry-run    # sans rien enregistrer
    python -m naosnatcher.run --limit 1    # forcer le nombre de bots

Code de sortie : 0 si le cycle s'est déroulé sans échec, 1 sinon — de quoi
laisser le planificateur signaler un problème.
"""

import argparse
import sys
from datetime import datetime

from . import state, sync


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m naosnatcher.run",
        description="Lance une synchronisation Janitor ➜ Saucepan.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="aller jusqu'au collage, sans rien enregistrer")
    parser.add_argument("--limit", type=int, default=None,
                        help="nombre de bots pour ce cycle (par défaut : daily_limit)")
    parser.add_argument("--force", action="store_true",
                        help="ignorer le fait qu'un cycle a déjà eu lieu aujourd'hui")
    args = parser.parse_args(argv)

    settings = state.load_settings()

    if not settings.get("enabled", True) and not args.force:
        print("Synchronisation désactivée dans les réglages.")
        return 0

    # Le planificateur peut relancer la tâche (session ouverte tardivement,
    # reprise après veille). Sans ce garde-fou, on enverrait un second lot le
    # même jour.
    if not args.force and not args.dry_run:
        last = settings.get("last_run") or ""
        if last[:10] == datetime.now().strftime("%Y-%m-%d"):
            print(f"Un cycle a déjà eu lieu aujourd'hui ({last}). "
                  "Utilisez --force pour en lancer un autre.")
            return 0

    if args.limit is not None:
        settings = dict(settings, daily_limit=args.limit)

    def say(line):
        print(line, flush=True)

    try:
        results = sync.full_sync(settings, say, dry_run=args.dry_run)
    except Exception as exc:                                       # noqa: BLE001
        state.log(f"❌ Cycle interrompu : {type(exc).__name__}: {exc}")
        print(f"Échec : {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if results.get("locked"):
        print("Un autre cycle est déjà en cours — rien à faire.")
        return 0

    if not args.dry_run:
        state.set_setting("last_run", datetime.now().isoformat(timespec="seconds"))

    print(f"Terminé : {results.get('ok', 0)} réussi(s), "
          f"{results.get('failed', 0)} échec(s), "
          f"{results.get('queued', 0)} en attente.")
    return 1 if results.get("failed") else 0


if __name__ == "__main__":
    sys.exit(main())
