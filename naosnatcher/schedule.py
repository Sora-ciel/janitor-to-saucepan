"""Synchronisation quotidienne confiée au système, fenêtre fermée ou non.

    Windows : une tâche du Planificateur (« Naosnatcher »), avec rattrapage
              si le PC était éteint à l'heure prévue.
    Linux   : un minuteur systemd utilisateur (`naosnatcher.timer`), même
              comportement grâce à `Persistent=true`.

Les deux lancent un cycle sans interface (`naosnatcher.run`). Le verrou
d'exécution et `last_run` empêchent tout doublon avec la fenêtre.
"""

import os
import subprocess
import sys

from . import config

TASK_NAME = "Naosnatcher"
UNIT_DIR = os.path.expanduser("~/.config/systemd/user")


class ScheduleError(RuntimeError):
    pass


def sync_command(program=None):
    """La commande qui lance un cycle sans interface : [programme, args…].

    `program` : le .exe à lancer, quand ce n'est pas celui qui tourne (une
    installation fraîche, lancée depuis Téléchargements).
    """
    if program or config.FROZEN:
        return [program or sys.executable, "--sync"]
    python = sys.executable
    if sys.platform == "win32":
        # pythonw : pas de console qui s'ouvre chaque matin.
        candidate = os.path.join(os.path.dirname(python), "pythonw.exe")
        if os.path.isfile(candidate):
            python = candidate
    return [python, "-m", "naosnatcher.run"]


def _run(args):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(args, capture_output=True, text=True,
                            creationflags=flags)
    if result.returncode != 0:
        raise ScheduleError((result.stderr or result.stdout or "").strip()
                            or f"échec de {args[0]}")
    return result.stdout


def _ps_quote(text):
    return "'" + str(text).replace("'", "''") + "'"


# ── Windows ─────────────────────────────────────────────────────────────────

def _install_windows(hour, minute, exe=None):
    program, *args = sync_command(exe)
    workdir = os.path.dirname(program) if (exe or config.FROZEN) else config.ROOT
    script = (
        f"$a = New-ScheduledTaskAction -Execute {_ps_quote(program)}"
        + (f" -Argument {_ps_quote(subprocess.list2cmdline(args))}" if args else "")
        + f" -WorkingDirectory {_ps_quote(workdir)};"
        f"$t = New-ScheduledTaskTrigger -Daily -At '{hour:02d}:{minute:02d}';"
        # Rattrapage : PC éteint à l'heure prévue → lancement au démarrage.
        "$s = New-ScheduledTaskSettingsSet -StartWhenAvailable "
        "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        "-ExecutionTimeLimit (New-TimeSpan -Minutes 30);"
        f"Register-ScheduledTask -TaskName {_ps_quote(TASK_NAME)} -Action $a "
        "-Trigger $t -Settings $s -Force | Out-Null"
    )
    _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])


def _uninstall_windows():
    _run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
          f"Unregister-ScheduledTask -TaskName {_ps_quote(TASK_NAME)} "
          "-Confirm:$false -ErrorAction SilentlyContinue"])


def _installed_windows():
    try:
        out = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                    f"if (Get-ScheduledTask -TaskName {_ps_quote(TASK_NAME)} "
                    "-ErrorAction SilentlyContinue) { 'yes' }"])
    except ScheduleError:
        return False
    return "yes" in out


# ── Linux ───────────────────────────────────────────────────────────────────

def _install_linux(hour, minute, exe=None):
    command = " ".join(f'"{part}"' for part in sync_command(exe))
    os.makedirs(UNIT_DIR, exist_ok=True)
    with open(os.path.join(UNIT_DIR, "naosnatcher.service"), "w") as f:
        f.write(
            "[Unit]\n"
            "Description=Naosnatcher daily sync (Janitor -> Saucepan)\n"
            "After=graphical-session.target\n"
            f"ConditionPathExists={sync_command(exe)[0]}\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            # Rattrapage juste après l'ouverture de session : on laisse au
            # bureau le temps d'exporter DISPLAY avant d'ouvrir le navigateur.
            "ExecStartPre=/bin/sleep 60\n"
            f"WorkingDirectory={config.ROOT}\n"
            f"ExecStart={command}\n"
            "TimeoutStartSec=30min\n"
        )
    with open(os.path.join(UNIT_DIR, "naosnatcher.timer"), "w") as f:
        f.write(
            "[Unit]\n"
            "Description=Run Naosnatcher every day\n\n"
            "[Timer]\n"
            f"OnCalendar=*-*-* {hour:02d}:{minute:02d}:00\n"
            "Persistent=true\n\n"
            "[Install]\n"
            "WantedBy=timers.target\n"
        )
    _run(["systemctl", "--user", "daemon-reload"])
    _run(["systemctl", "--user", "enable", "--now", "naosnatcher.timer"])


def _uninstall_linux():
    try:
        _run(["systemctl", "--user", "disable", "--now", "naosnatcher.timer"])
    except ScheduleError:
        pass
    for name in ("naosnatcher.timer", "naosnatcher.service"):
        try:
            os.remove(os.path.join(UNIT_DIR, name))
        except OSError:
            pass
    try:
        _run(["systemctl", "--user", "daemon-reload"])
    except ScheduleError:
        pass


def _installed_linux():
    try:
        return _run(["systemctl", "--user", "is-enabled",
                     "naosnatcher.timer"]).strip() == "enabled"
    except (ScheduleError, OSError):
        return False


# ── Interface commune ───────────────────────────────────────────────────────

def install(hour, minute, program=None):
    if sys.platform == "win32":
        _install_windows(int(hour), int(minute), program)
    else:
        _install_linux(int(hour), int(minute), program)


def uninstall():
    if sys.platform == "win32":
        _uninstall_windows()
    else:
        _uninstall_linux()


def is_installed():
    return _installed_windows() if sys.platform == "win32" else _installed_linux()
