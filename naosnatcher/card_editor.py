"""Onglet « Créer une carte » : une carte de personnage faite à la main.

On choisit une image, on remplit la fiche, et l'on obtient un PNG portant la
fiche intégrée — le même format que les cartes tirées de Janitor, écrit par
`card.write_card`, donc avec les mêmes correspondances de champs (celles que
l'importeur de Janitor attend : définition dans « Personality », présentation
dans la description publique).

On peut aussi rouvrir une carte existante pour la retoucher.
"""

import io
import os

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import (
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from . import card, config

IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.avif)"
PREVIEW = 240


def _area(placeholder, height):
    box = QPlainTextEdit()
    box.setPlaceholderText(placeholder)
    box.setMinimumHeight(height)
    return box


class CardEditor(QWidget):
    """Formulaire de carte de personnage."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image_path = None

        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(
            "Fabriquez une carte à partir de votre propre image et de votre "
            "fiche. Elle s'importe dans Janitor en déposant l'image sur l'avatar "
            "d'un nouveau bot, ainsi que dans SillyTavern, Chub, etc."))

        body = QHBoxLayout()

        # -- Colonne image ---------------------------------------------------
        left = QVBoxLayout()
        self.preview = QLabel("Aucune image")
        self.preview.setFixedSize(PREVIEW, PREVIEW)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("border: 1px dashed #888;")
        left.addWidget(self.preview)
        pick = QPushButton("Choisir l'image…")
        pick.clicked.connect(self._pick_image)
        left.addWidget(pick)
        drop = QPushButton("Retirer l'image")
        drop.clicked.connect(lambda: self._set_image(None))
        left.addWidget(drop)
        hint = QLabel("Sans image, la carte reçoit un fond neutre.")
        hint.setWordWrap(True)
        hint.setFixedWidth(PREVIEW)
        left.addWidget(hint)
        left.addStretch(1)
        body.addLayout(left)

        # -- Colonne fiche ---------------------------------------------------
        form_host = QWidget()
        form = QFormLayout(form_host)

        self.title = QLineEdit()
        self.title.setPlaceholderText("Ryomen Sukuna | Cumbersome Doll")
        form.addRow("Titre du bot :", self.title)

        self.chat_name = QLineEdit()
        self.chat_name.setPlaceholderText("Sukuna")
        form.addRow("Nom en conversation :", self.chat_name)

        self.personality = _area(
            "La définition du personnage (case « Personality » de Janitor).", 180)
        form.addRow("Personnalité :", self.personality)

        self.scenario = _area("Contexte de la scène (facultatif).", 70)
        form.addRow("Scénario :", self.scenario)

        self.first_message = _area("Le message d'ouverture.", 140)
        form.addRow("Premier message :", self.first_message)

        self.alternates = _area(
            "Facultatif. Séparez chaque message par une ligne ne contenant que "
            f"{card.GREETING_SEPARATOR}", 70)
        form.addRow("Messages alternatifs :", self.alternates)

        self.examples = _area("Exemples de dialogue (facultatif).", 70)
        form.addRow("Exemples :", self.examples)

        self.description = _area(
            "La présentation publique. Texte libre — les paragraphes sont "
            "conservés — ou HTML.", 120)
        form.addRow("Présentation :", self.description)

        self.tags = QLineEdit()
        self.tags.setPlaceholderText("male, villain, dom, angst")
        form.addRow("Tags :", self.tags)

        self.creator = QLineEdit()
        form.addRow("Créateur :", self.creator)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_host)
        body.addWidget(scroll, 1)
        outer.addLayout(body, 1)

        # -- Actions ---------------------------------------------------------
        actions = QHBoxLayout()
        load = QPushButton("Ouvrir une carte existante…")
        load.clicked.connect(self._load_card)
        clear = QPushButton("Nouvelle carte")
        clear.clicked.connect(self._clear)
        folder = QPushButton("Dossier des cartes")
        folder.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(config.CARDS_DIR)))
        save = QPushButton("Enregistrer la carte PNG…")
        save.setDefault(True)
        save.clicked.connect(self._save)
        for b in (load, clear, folder):
            actions.addWidget(b)
        actions.addStretch(1)
        actions.addWidget(save)
        outer.addLayout(actions)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)

    # -- Image ---------------------------------------------------------------

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Image de la carte", config.CARDS_DIR, IMAGE_FILTER)
        if path:
            self._set_image(path)

    def _set_image(self, path):
        self.image_path = path
        if not path:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("Aucune image")
            return
        pixmap = self._load_pixmap(path)
        if pixmap.isNull():
            self.preview.setText("Aperçu indisponible")
        else:
            self.preview.setPixmap(pixmap.scaled(
                PREVIEW, PREVIEW, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    @staticmethod
    def _load_pixmap(path):
        """Aperçu via Pillow : Qt ne lit pas le webp ni l'avif partout."""
        pixmap = QPixmap()
        try:
            from PIL import Image
            with Image.open(path) as img:
                img.seek(0)
                buffer = io.BytesIO()
                img.convert("RGBA").save(buffer, "PNG")
            pixmap.loadFromData(buffer.getvalue(), "PNG")
        except Exception:                                        # noqa: BLE001
            pixmap.load(path)
        return pixmap

    # -- Fiche ---------------------------------------------------------------

    def _fields(self):
        alternates = []
        for block in self.alternates.toPlainText().split(
                "\n" + card.GREETING_SEPARATOR + "\n"):
            block = block.strip()
            if block and block != card.GREETING_SEPARATOR:
                alternates.append(block)
        return {
            "title": self.title.text(),
            "chat_name": self.chat_name.text(),
            "personality": self.personality.toPlainText(),
            "description": self.description.toPlainText(),
            "scenario": self.scenario.toPlainText(),
            "first_message": self.first_message.toPlainText(),
            "alternate_greetings": alternates,
            "example_dialogs": self.examples.toPlainText(),
            "tags": self.tags.text(),
            "creator": self.creator.text(),
        }

    def _fill(self, fields):
        self.title.setText(fields.get("title", ""))
        self.chat_name.setText(fields.get("chat_name", ""))
        self.personality.setPlainText(fields.get("personality", ""))
        self.description.setPlainText(fields.get("description", ""))
        self.scenario.setPlainText(fields.get("scenario", ""))
        self.first_message.setPlainText(fields.get("first_message", ""))
        separator = "\n" + card.GREETING_SEPARATOR + "\n"
        self.alternates.setPlainText(
            separator.join(fields.get("alternate_greetings") or []))
        self.examples.setPlainText(fields.get("example_dialogs", ""))
        self.tags.setText(fields.get("tags", ""))
        self.creator.setText(fields.get("creator", ""))

    def _clear(self):
        self._fill({})
        self._set_image(None)
        self.status.setText("")

    def _load_card(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Ouvrir une carte", config.CARDS_DIR, "Cartes PNG (*.png)")
        if not path:
            return
        try:
            data = card.read_card(path)
        except Exception as exc:                                 # noqa: BLE001
            QMessageBox.warning(
                self, "Naosnatcher",
                f"Cette image ne contient pas de fiche lisible.\n\n{exc}")
            return
        self._fill(card.fields_from_card(data))
        # L'image de la carte devient l'avatar : réenregistrer la carte la
        # garde, avec une fiche neuve.
        self._set_image(path)
        self.status.setText(f"Carte ouverte : {path}")

    def _save(self):
        fields = self._fields()
        if not (fields["title"].strip() or fields["chat_name"].strip()):
            QMessageBox.warning(self, "Naosnatcher",
                                "Donnez au moins un titre ou un nom au bot.")
            return
        if not fields["personality"].strip():
            answer = QMessageBox.question(
                self, "Naosnatcher",
                "La personnalité est vide : le bot n'aura pas de définition.\n\n"
                "Enregistrer quand même ?")
            if answer != QMessageBox.StandardButton.Yes:
                return

        stem = card.safe_name(fields["title"] or fields["chat_name"])
        suggested = os.path.join(config.CARDS_DIR, f"{stem}.png")
        path, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer la carte", suggested, "Carte PNG (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"

        try:
            written = card.write_card(card.fiche_from_fields(fields),
                                      image_path=self.image_path,
                                      log=lambda m: None, path=path)
        except Exception as exc:                                 # noqa: BLE001
            QMessageBox.warning(self, "Naosnatcher",
                                f"Carte non enregistrée :\n\n{exc}")
            return
        self.status.setText(f"✅ Carte enregistrée : {written}")
