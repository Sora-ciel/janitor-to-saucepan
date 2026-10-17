"""Point d'entrée unique, celui du programme construit (.exe) comme des sources.

    Naosnatcher.exe                 la fenêtre
    Naosnatcher.exe --sync [...]    un cycle sans interface (tâche planifiée)
    Naosnatcher.exe --uninstall     désinstallation (« Applications installées »)
"""

import os
import sys

ATTACH_PARENT_PROCESS = -1


def _wire_up_output():
    """Un .exe sans console n'a ni stdout ni stderr : le premier print
    l'abattrait. Lancé depuis un terminal, il s'y raccroche ; sinon, il écrit
    dans le vide — le journal, lui, va dans data/sync.log."""
    if os.name == "nt" and getattr(sys, "frozen", False):
        try:
            import ctypes
            if ctypes.WinDLL("kernel32").AttachConsole(ATTACH_PARENT_PROCESS):
                for name in ("stdout", "stderr"):
                    try:
                        setattr(sys, name, open("CONOUT$", "w", buffering=1,
                                                encoding="utf-8"))
                    except OSError:
                        pass
        except OSError:
            pass
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))

    # Sortie redirigee (tube, fichier, tache planifiee) : Windows y applique
    # sa page de code locale, cp1252, qui ne connait ni « ⚠ » ni « ✅ ». Le
    # premier avertissement du journal abattait alors le cycle entier. On
    # force l'UTF-8, et `replace` garantit qu'un caractere exotique ne peut
    # plus jamais interrompre une synchronisation.
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        try:
            if (stream.encoding or "").lower().replace("-", "") != "utf8":
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _report_crash(error):
    """Sans console, une erreur fatale passerait inaperçue : on l'écrit et on
    dit où."""
    import traceback

    text = "".join(traceback.format_exception(error))
    path = None
    try:
        from . import config
        path = os.path.join(config.DATA_DIR, "crash.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:                                              # noqa: BLE001
        pass
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance() or QApplication(sys.argv[:1])
        QMessageBox.critical(
            None, "Naosnatcher",
            f"Naosnatcher a rencontré un problème et doit fermer.\n\n"
            f"{error or type(error).__name__}\n\nDétails : {path}")
        del app
    except Exception:                                              # noqa: BLE001
        pass
    print(text, file=sys.stderr)


def _uninstall(quiet):
    from . import install
    if not quiet:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        app = QApplication(sys.argv[:1])               # noqa: F841
        answer = QMessageBox.question(
            None, "Naosnatcher",
            "Désinstaller Naosnatcher ?\n\nLa synchronisation quotidienne sera "
            "arrêtée. Vos données (registre des bots, réglages, cartes) sont "
            "conservées pour une éventuelle réinstallation.")
        if answer != QMessageBox.StandardButton.Yes:
            return 0
    install.uninstall()
    if not quiet:
        QMessageBox.information(None, "Naosnatcher", "Naosnatcher est désinstallé.")
    return 0


def _main(argv):
    if "--sync" in argv:
        argv.remove("--sync")
        from . import run
        return run.main(argv)

    if "--uninstall" in argv:
        return _uninstall("--quiet" in argv)

    from . import app
    return app.main()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    _wire_up_output()
    try:
        sys.exit(_main(argv))
    except SystemExit:
        raise
    except BaseException as error:                                 # noqa: BLE001
        _report_crash(error)
        sys.exit(1)
