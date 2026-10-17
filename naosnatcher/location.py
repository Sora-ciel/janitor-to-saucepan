"""Choix de l'emplacement des donnees.

Par defaut les donnees vivent a cote de l'application (ou dans
le dossier local du systeme pour la version installee). On peut leur preferer
un dossier quelconque -- typiquement sur une partition visible depuis Windows
**et** depuis Linux, afin que les deux systemes travaillent sur le meme
registre et ne renvoient pas deux fois les memes bots.

Ce qui est partage : le registre, les reglages, le journal, les exports et les
cartes. Ce qui ne l'est pas : le profil du navigateur, propre a chaque systeme
(voir config.BROWSER_STATE).
"""

import os

from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout,
)

from . import config

SHARED = ("le registre des bots deja envoyes", "les reglages",
          "le journal", "les exports et les cartes")


def describe_current():
    """Phrase courte decrivant l'emplacement actuel et son origine."""
    origins = {
        "env": "impose par la variable NAOSNATCHER_DATA",
        "pointer": "choisi",
        "default": "par defaut",
    }
    return f"{config.ROOT}  ({origins.get(config.ROOT_SOURCE, config.ROOT_SOURCE)})"


def looks_usable(path):
    """(ok, message) -- le dossier peut-il accueillir les donnees ?"""
    if not path:
        return False, "Aucun dossier indique."
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".naosnatcher-ecriture")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
    except OSError as exc:
        return False, f"Dossier inutilisable : {exc}"
    return True, ""


def has_existing_data(path):
    """Le dossier contient-il deja un registre Naosnatcher ?"""
    for candidate in (os.path.join(path, "data", "seen_bots.json"),
                      os.path.join(path, "seen_bots.json")):
        if os.path.isfile(candidate):
            return True
    return False


class LocationDialog(QDialog):
    """Petite fenetre pour choisir ou ranger les donnees."""

    def __init__(self, parent=None, initial=None):
        super().__init__(parent)
        self.setWindowTitle("Emplacement des donnees")
        self.setMinimumWidth(560)
        box = QVBoxLayout(self)

        intro = QLabel(
            "<p>Ou Naosnatcher doit-il ranger <b>" + ", ".join(SHARED) + "</b> ?</p>"
            "<p>Un dossier visible depuis Windows et depuis Linux permet aux "
            "deux systemes de partager le meme registre : un bot envoye depuis "
            "l'un ne sera pas renvoye depuis l'autre.</p>"
            "<p style='color:#888'>Le profil du navigateur reste propre a "
            "chaque systeme : un profil Chromium pese des centaines de Mo et "
            "contient des chemins absolus.</p>")
        intro.setWordWrap(True)
        box.addWidget(intro)

        row = QHBoxLayout()
        self.field = QLineEdit(initial or config.ROOT)
        pick = QPushButton("Parcourir...")
        pick.clicked.connect(self._pick)
        row.addWidget(self.field, 1)
        row.addWidget(pick)
        box.addLayout(row)

        default_btn = QPushButton("Revenir a l'emplacement par defaut")
        default_btn.clicked.connect(
            lambda: self.field.setText(config.default_root()))
        box.addWidget(default_btn)

        self.note = QLabel("")
        self.note.setWordWrap(True)
        box.addWidget(self.note)
        self.field.textChanged.connect(self._refresh_note)
        self._refresh_note()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        box.addWidget(buttons)

    def _pick(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Dossier des donnees", self.field.text() or config.ROOT)
        if folder:
            self.field.setText(folder)

    def _refresh_note(self):
        path = self.field.text().strip()
        if path and has_existing_data(path):
            self.note.setText(
                "Ce dossier contient deja un registre Naosnatcher : il sera "
                "repris tel quel, rien ne sera ecrase.")
        else:
            self.note.setText(
                "Dossier neuf : le registre y sera cree. Si vous avez deja "
                "synchronise des bots ailleurs, pensez a importer "
                "l'installation precedente, sans quoi tout serait renvoye.")

    def chosen(self):
        return self.field.text().strip()

    def _accept(self):
        ok, message = looks_usable(self.chosen())
        if not ok:
            QMessageBox.warning(self, "Naosnatcher", message)
            return
        self.accept()


def ask_and_apply(parent=None, initial=None):
    """Demande un emplacement et l'enregistre. Renvoie le chemin, ou None.

    Le changement ne prend effet qu'au prochain demarrage : les chemins sont
    calcules une fois pour toutes a l'import de `config`.
    """
    dialog = LocationDialog(parent, initial)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    path = dialog.chosen()
    if os.path.abspath(path) == os.path.abspath(config.default_root()):
        config.write_pointer(None)          # retour au defaut : plus de repere
        return config.default_root()
    return config.write_pointer(path)
