"""Installation de Naosnatcher.exe sur un PC Windows — sur le modèle de KritraK.

Il n'y a qu'un fichier à distribuer : Naosnatcher.exe. Lancé depuis
Téléchargements, il propose de s'installer : copie dans le dossier des
programmes de l'utilisateur, raccourci dans le menu Démarrer (et sur le
bureau), inscription dans « Applications installées » avec une désinstallation
qui fonctionne.

Tout se passe sous HKCU et %LOCALAPPDATA% : jamais de droits administrateur.
Une désinstallation retire le programme et la tâche planifiée, mais garde les
données (registre des bots, réglages, cartes) — elles servent à une
réinstallation.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__

try:
    import winreg
except ImportError:                                                # pas Windows
    winreg = None

APP_NAME = "Naosnatcher"
EXE_NAME = "Naosnatcher.exe"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Naosnatcher"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def install_dir():
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "Programs" / APP_NAME


def installed_exe():
    return install_dir() / EXE_NAME


def _start_menu_shortcut():
    appdata = os.environ.get("APPDATA") or str(Path.home())
    return Path(appdata) / "Microsoft/Windows/Start Menu/Programs" / (APP_NAME + ".lnk")


def _desktop_shortcut():
    return Path.home() / "Desktop" / (APP_NAME + ".lnk")


def is_installed():
    return installed_exe().exists()


def running_from_install():
    if not is_frozen():
        return False
    try:
        return Path(sys.executable).resolve() == installed_exe().resolve()
    except OSError:
        return False


def should_offer_install():
    """Un .exe Windows lancé ailleurs que depuis son dossier d'installation."""
    return sys.platform == "win32" and is_frozen() and not running_from_install()


def _quoted(value):
    # Chaîne PowerShell entre apostrophes : une apostrophe se double.
    return "'%s'" % str(value).replace("'", "''")


def _make_shortcut(path, target):
    """Un raccourci .lnk, écrit par PowerShell — sans dépendance de plus."""
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut(%s);"
        "$s.TargetPath = %s;"
        "$s.WorkingDirectory = %s;"
        "$s.Description = 'Janitor AI vers Saucepan AI';"
        "$s.IconLocation = %s;"
        "$s.Save()"
    ) % (_quoted(path), _quoted(target), _quoted(Path(target).parent),
         _quoted(target))
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, creationflags=NO_WINDOW)
    return result.returncode == 0


def _register(target):
    if winreg is None:
        return
    try:
        size_kb = int(target.stat().st_size / 1024)
    except OSError:
        size_kb = 0
    values = {
        "DisplayName": APP_NAME,
        "DisplayVersion": __version__,
        "Publisher": APP_NAME,
        "DisplayIcon": str(target),
        "InstallLocation": str(target.parent),
        "UninstallString": '"%s" --uninstall' % target,
        "QuietUninstallString": '"%s" --uninstall --quiet' % target,
    }
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, size_kb)


def _unregister():
    if winreg is None:
        return
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass


def install(desktop_shortcut=True):
    """Copie ce .exe en place et l'inscrit. Renvoie le chemin installé."""
    if not is_frozen():
        raise OSError("seul Naosnatcher.exe peut s'installer lui-même")
    source = Path(sys.executable).resolve()
    target = installed_exe()
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or source != target.resolve():
        # Windows refuse d'écraser un .exe en cours d'exécution : une mise à
        # jour suppose que la copie installée a été fermée.
        shutil.copy2(source, target)

    _make_shortcut(_start_menu_shortcut(), target)
    if desktop_shortcut:
        _make_shortcut(_desktop_shortcut(), target)
    _register(target)

    # Une tâche planifiée créée depuis l'ancienne copie pointerait vers elle :
    # on la redirige vers le programme installé.
    from . import schedule, state
    try:
        if schedule.is_installed():
            s = state.load_settings()
            schedule.install(s.get("daily_hour", 8), s.get("daily_minute", 0),
                             program=str(target))
    except Exception:                                              # noqa: BLE001
        pass
    return target


def launch_installed():
    target = installed_exe()
    if not target.exists():
        return False
    subprocess.Popen([str(target)], close_fds=True,
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    return True


def uninstall():
    """Défait tout ce qu'a fait install(), sauf les données."""
    from . import schedule
    try:
        schedule.uninstall()
    except Exception:                                              # noqa: BLE001
        pass
    _unregister()
    for shortcut in (_start_menu_shortcut(), _desktop_shortcut()):
        try:
            shortcut.unlink()
        except OSError:
            pass
    return _remove_install_dir()


def _remove_install_dir():
    """Un .exe en cours d'exécution ne peut pas s'effacer : un PowerShell
    détaché attend la fin de ce processus, puis supprime le dossier. Le chemin
    passe par une variable d'environnement, sûre pour les accents."""
    folder = install_dir()
    if not folder.exists():
        return True
    if not running_from_install():
        shutil.rmtree(folder, ignore_errors=True)
        return not folder.exists()
    waiter = (
        "$target = $env:NAOSNATCHER_REMOVE;"
        "for ($i = 0; $i -lt 30; $i++) {"
        "  Start-Sleep -Milliseconds 500;"
        "  if (-not (Test-Path -LiteralPath $target)) { break };"
        "  Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue"
        "}"
    )
    subprocess.Popen(
        ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
         "-Command", waiter],
        env=dict(os.environ, NAOSNATCHER_REMOVE=str(folder)),
        creationflags=NO_WINDOW, close_fds=True)
    return True
