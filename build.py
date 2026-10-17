"""Construit Naosnatcher.exe — le seul fichier à distribuer.

    python build.py            (sous Windows)
    python build.py --clean    repart de zéro

Produit dist/Naosnatcher.exe : un exécutable fenêtré, sans console ni Python à
installer. Lancé, il propose de s'installer (voir naosnatcher/install.py).
Même principe que KritraK.

Les dépendances manquantes (requirements.txt + PyInstaller) sont installées
dans le Python qui lance ce script. Sous Linux, le même script produit
dist/Naosnatcher, un exécutable Linux.
"""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"
NAME = "Naosnatcher"

sys.path.insert(0, str(ROOT))

VERSION_RESOURCE = """
VSVersionInfo(
  ffi=FixedFileInfo(filevers=%(tuple)s, prodvers=%(tuple)s, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040C04B0', [
        StringStruct('CompanyName', 'Naosnatcher'),
        StringStruct('FileDescription', 'Naosnatcher - Janitor AI vers Saucepan AI'),
        StringStruct('FileVersion', '%(version)s'),
        StringStruct('InternalName', 'Naosnatcher'),
        StringStruct('OriginalFilename', 'Naosnatcher.exe'),
        StringStruct('ProductName', 'Naosnatcher'),
        StringStruct('ProductVersion', '%(version)s')])]),
    VarFileInfo([VarStruct('Translation', [1036, 1200])])
  ]
)
"""

# Module importé → paquet pip.
NEEDED = {"PyInstaller": "pyinstaller", "PyQt6": "PyQt6",
          "playwright": "playwright", "requests": "requests", "PIL": "Pillow"}

# Modules Qt inutiles ici : les écarter allège nettement l'exécutable.
QT_EXCLUDES = ["QtWebEngineCore", "QtWebEngineWidgets", "QtWebEngineQuick",
               "QtQml", "QtQuick", "QtQuick3D", "QtMultimedia",
               "QtMultimediaWidgets", "QtBluetooth", "QtPdf", "QtPdfWidgets",
               "QtDesigner", "QtSql", "QtTest", "QtOpenGL", "QtOpenGLWidgets",
               "QtSpatialAudio", "QtSensors", "QtSerialPort", "QtPositioning",
               "QtRemoteObjects", "QtTextToSpeech", "QtNfc", "QtSvg", "QtHelp"]


def ensure_dependencies():
    missing = [pkg for mod, pkg in NEEDED.items()
               if importlib.util.find_spec(mod) is None]
    if missing:
        print("Installation de :", ", ".join(missing))
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])


def build():
    ensure_dependencies()
    from naosnatcher import __version__

    BUILD.mkdir(exist_ok=True)
    parts = tuple(int(p) for p in __version__.split(".")) + (0,)
    version_file = BUILD / "version_info.txt"
    version_file.write_text(
        VERSION_RESOURCE % {"tuple": str(parts), "version": __version__},
        encoding="utf-8")

    # Mise en forme livrée avec l'exécutable : les valeurs neutres du code,
    # jamais le data/housestyle.json de la machine qui construit — il porte la
    # signature et les liens de son auteur, que chaque installation
    # recevrait sinon au bas de ses fiches.
    import json
    from naosnatcher import housestyle
    neutral = BUILD / "housestyle.json"
    neutral.write_text(json.dumps(housestyle.DEFAULTS, ensure_ascii=False,
                                  indent=2), encoding="utf-8")

    sep = ";" if sys.platform == "win32" else ":"
    data = [
        (ROOT / "data" / "saucepan_tags.json", "data"),
        (neutral, "data"),
        (ROOT / "packaging" / "naosnatcher.png", "packaging"),
    ]
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",          # un seul fichier à distribuer
        "--windowed",         # jamais de fenêtre de console
        "--name", NAME,
        "--icon", str(ROOT / "packaging" / "naosnatcher.ico"),
        "--version-file", str(version_file),
        "--distpath", str(DIST),
        "--workpath", str(BUILD / "work"),
        "--specpath", str(BUILD),
        "--paths", str(ROOT),
        # Le « driver » de Playwright (Node) sert à se raccrocher au
        # navigateur de l'utilisateur ; aucun navigateur n'est embarqué.
        "--collect-data", "playwright",
        "--hidden-import", "naosnatcher.app",
        "--hidden-import", "naosnatcher.run",
        "--exclude-module", "tkinter",
        "--exclude-module", "pytest",
    ]
    for module in QT_EXCLUDES:
        command += ["--exclude-module", f"PyQt6.{module}"]
    for src, dest in data:
        command += ["--add-data", f"{src}{sep}{dest}"]
    command.append(str(ROOT / "packaging" / "entry.py"))

    print(" ".join(command))
    result = subprocess.run(command)
    if result.returncode != 0:
        return result.returncode

    exe = DIST / (NAME + (".exe" if sys.platform == "win32" else ""))
    print(f"\nconstruit : {exe} ({exe.stat().st_size / 1024 / 1024:.1f} Mo)")
    print("Ce fichier suffit : lancé, il propose de s'installer.")
    return 0


def clean():
    shutil.rmtree(BUILD, ignore_errors=True)
    shutil.rmtree(DIST, ignore_errors=True)


if __name__ == "__main__":
    if "--clean" in sys.argv:
        clean()
    sys.exit(build())
