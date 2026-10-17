"""Rapport par courriel des aperçus trop longs.

Saucepan limite la description courte à 140 caractères. Quand le paragraphe
d'accroche dépasse cette limite, la synchronisation retombe sur le titre du
bot : c'est correct, mais moins parlant qu'un vrai résumé. Ce module rassemble
ces cas et en fait un message, pour que l'auteur sache lesquels reprendre.

    python -m naosnatcher.notify                 # affiche le rapport
    python -m naosnatcher.notify --send          # l'envoie par courriel
    python -m naosnatcher.notify --all           # y compris les cas déjà signalés

Le mot de passe n'est **jamais** écrit dans un fichier : il est lu dans la
variable d'environnement `NAOSNATCHER_SMTP_PASSWORD`. Les autres réglages
vivent dans `data/settings.json` :

    "mail": {
      "smtp_host": "smtp.gmail.com",
      "smtp_port": 587,
      "username":  "vous@exemple.com",
      "from":      "vous@exemple.com",
      "to":        "vous@exemple.com"
    }
"""

import argparse
import os
import smtplib
import sys
from email.message import EmailMessage

from . import state

SUBJECT = "Naosnatcher — {count} aperçu(s) à réécrire"

PASSWORD_ENV = "NAOSNATCHER_SMTP_PASSWORD"


def build_report(entries):
    """Compose le corps du message. Renvoie du texte brut."""
    lines = [
        f"{len(entries)} bot(s) synchronisés dont le paragraphe d'accroche "
        "dépassait les 140 caractères autorisés par Saucepan.",
        "",
        "Pour ceux-là, c'est le titre qui a servi d'aperçu. Un résumé écrit "
        "à la main serait plus parlant.",
        "",
    ]
    for entry in entries:
        lines.append(f"• {entry.get('name') or entry.get('id')}")
        lines.append(f"    paragraphe : {entry.get('paragraph_length')} caractères "
                     f"(limite {entry.get('limit', 140)})")
        lines.append(f"    aperçu utilisé : « {entry.get('used_instead')} »")
        if entry.get("saucepan_url"):
            lines.append(f"    {entry['saucepan_url']}")
        lines.append(f"    synchronisé le {entry.get('at')}")
        lines.append("")
    return "\n".join(lines).strip()


def mail_settings():
    settings = state.load_settings().get("mail") or {}
    missing = [k for k in ("smtp_host", "username", "from", "to")
               if not settings.get(k)]
    return settings, missing


def send(entries, settings, password):
    message = EmailMessage()
    message["Subject"] = SUBJECT.format(count=len(entries))
    message["From"] = settings["from"]
    message["To"] = settings["to"]
    message.set_content(build_report(entries))

    port = int(settings.get("smtp_port", 587))
    with smtplib.SMTP(settings["smtp_host"], port, timeout=30) as server:
        server.starttls()
        server.login(settings["username"], password)
        server.send_message(message)
    return message["To"]


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m naosnatcher.notify",
        description="Signale les aperçus qui ont dû être remplacés par le titre.",
    )
    parser.add_argument("--send", action="store_true",
                        help="envoyer le rapport par courriel (sinon, affichage seul)")
    parser.add_argument("--all", action="store_true",
                        help="inclure les cas déjà signalés")
    args = parser.parse_args(argv)

    entries = state.load_overflows(pending_only=not args.all)

    if not entries:
        print("Aucun aperçu à signaler.")
        return 0

    report = build_report(entries)

    if not args.send:
        print(report)
        print()
        print(f"({len(entries)} cas — ajoutez --send pour l'envoyer par courriel.)")
        return 0

    settings, missing = mail_settings()
    if missing:
        print("Configuration courriel incomplète dans data/settings.json : "
              + ", ".join(missing), file=sys.stderr)
        print('Exemple : "mail": {"smtp_host": "...", "smtp_port": 587, '
              '"username": "...", "from": "...", "to": "..."}', file=sys.stderr)
        return 1

    password = os.environ.get(PASSWORD_ENV)
    if not password:
        print(f"Variable d'environnement {PASSWORD_ENV} absente. "
              "Le mot de passe n'est volontairement pas stocké sur le disque.",
              file=sys.stderr)
        return 1

    try:
        recipient = send(entries, settings, password)
    except Exception as exc:                                       # noqa: BLE001
        print(f"Envoi impossible : {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    state.mark_overflows_notified(e["id"] for e in entries)
    print(f"Rapport envoyé à {recipient} ({len(entries)} cas).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
