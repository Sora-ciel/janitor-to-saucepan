"""Assistant de premier lancement : chaque étape de la mise en route, guidée.

S'ouvre tout seul quand rien n'est encore configuré, et reste accessible
depuis l'onglet Configuration. Rien n'est enregistré avant « Terminer », à
l'exception du navigateur choisi et d'une éventuelle reprise de données, qui
servent dès les étapes suivantes.
"""

import sys

from PyQt6.QtWidgets import (
    QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QRadioButton, QSpinBox, QVBoxLayout, QWizard,
    QWizardPage,
)

from . import config, driver, schedule, state, sync, worker

DEFAULT_SAUCEPAN_EDITOR = "https://saucepan.ai/editor/new/settings"


def _text(html):
    label = QLabel(html)
    label.setWordWrap(True)
    label.setOpenExternalLinks(True)
    return label


class _Page(QWizardPage):
    def __init__(self, title, subtitle=""):
        super().__init__()
        self.setTitle(title)
        if subtitle:
            self.setSubTitle(subtitle)
        self.box = QVBoxLayout(self)

    def run(self, fn, *args, done=None, status=None):
        """Tâche longue (navigateur) sans figer l'assistant."""
        wiz = self.wizard()
        if status:
            status.setText("⏳ …")

        def failed(message):
            if status:
                status.setText(f"❌ {message}")

        wiz._jobs.append(worker.start(
            wiz, fn, *args, on_finished=done, on_failed=failed))


class WelcomePage(_Page):
    def __init__(self):
        super().__init__("Bienvenue dans Naosnatcher")
        self.box.addWidget(_text(
            "<p>Naosnatcher recopie chaque jour vos nouveaux bots <b>Janitor AI</b> "
            "sur <b>Saucepan AI</b>, et peut créer leurs <b>cartes de "
            "personnage</b> (une image PNG qui contient la fiche du bot).</p>"
            "<p>Cet assistant vous guide en quelques étapes :</p>"
            "<ol><li>choisir le navigateur que l'application pilotera ;</li>"
            "<li>vous y connecter à Janitor et à Saucepan ;</li>"
            "<li>indiquer ce qu'il faut faire des bots déjà publiés ;</li>"
            "<li>choisir l'heure de la synchronisation quotidienne.</li></ol>"
            "<p>Comptez cinq minutes. Tout reste modifiable ensuite.</p>"
        ))
        self.box.addSpacing(12)
        self.box.addWidget(_text(
            "<b>Vous utilisiez déjà Naosnatcher ?</b> Reprenez son registre : "
            "sans lui, l'application croirait n'avoir jamais rien envoyé."))
        row = QHBoxLayout()
        button = QPushButton("Importer une installation précédente…")
        button.clicked.connect(self._import)
        self.status = QLabel("")
        row.addWidget(button)
        row.addWidget(self.status, 1)
        self.box.addLayout(row)
        self.box.addStretch(1)

    def _import(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Dossier de l'ancienne installation (celui qui contient « data »)")
        if not folder:
            return
        try:
            copied = state.import_data(folder)
        except OSError as exc:
            QMessageBox.warning(self, "Naosnatcher", str(exc))
            return
        known = len(state.load_seen())
        self.status.setText(f"✅ {known} bot(s) repris ({', '.join(copied)})")
        self.wizard().reload_settings()


class BrowserPage(_Page):
    def __init__(self):
        super().__init__(
            "1. Le navigateur",
            "Naosnatcher n'a pas de navigateur à lui : il pilote le vôtre.")
        self.box.addWidget(_text(
            "<p>Les sites refusent les navigateurs automatisés ; c'est donc "
            "<b>vous</b> qui vous connectez, dans une vraie fenêtre, et "
            "l'application réutilise ensuite cette session.</p>"
            "<p>Une fenêtre à part est utilisée, avec son propre profil : vos "
            "onglets habituels ne sont pas touchés. Vivaldi, Chrome, Edge, "
            "Brave ou Chromium conviennent.</p>"))

        form = QFormLayout()
        self.path = QLineEdit()
        self.path.setReadOnly(True)
        pick = QPushButton("Choisir…")
        pick.clicked.connect(self._pick)
        row = QHBoxLayout()
        row.addWidget(self.path, 1)
        row.addWidget(pick)
        form.addRow("Navigateur :", row)
        self.box.addLayout(form)

        row = QHBoxLayout()
        open_btn = QPushButton("Ouvrir le navigateur")
        open_btn.clicked.connect(self._open)
        self.status = QLabel("")
        row.addWidget(open_btn)
        row.addWidget(self.status, 1)
        self.box.addLayout(row)
        self.box.addStretch(1)

    def initializePage(self):
        found = self.wizard().settings.get("browser_path") or driver.find_browser()
        self.path.setText(found or "")
        if not found:
            self.status.setText(
                "⚠ Aucun navigateur trouvé automatiquement — utilisez « Choisir… ».")

    def _pick(self):
        filt = "Programmes (*.exe)" if sys.platform == "win32" else "Tous (*)"
        path, _ = QFileDialog.getOpenFileName(self, "Navigateur", "", filt)
        if path:
            self.path.setText(path)
            self.wizard().settings["browser_path"] = path
            state.set_setting("browser_path", path)

    def _open(self):
        try:
            info = driver.ensure_browser(self.path.text() or None)
        except Exception as exc:                                   # noqa: BLE001
            self.status.setText(f"❌ {exc}")
            return
        self.status.setText(f"✅ {info.get('Browser', 'navigateur')} ouvert")

    def validatePage(self):
        if self.path.text() or driver.is_cdp_up():
            return True
        QMessageBox.warning(self, "Naosnatcher",
                            "Choisissez d'abord un navigateur.")
        return False


class LoginPage(_Page):
    def __init__(self):
        super().__init__(
            "2. Connexion aux deux sites",
            "Dans la fenêtre ouverte par Naosnatcher, pas dans votre navigateur habituel.")
        self.box.addWidget(_text(
            "<ol><li>Cliquez <b>Ouvrir les deux sites</b> : un onglet Janitor "
            "et un onglet Saucepan s'ouvrent dans la fenêtre pilotée.</li>"
            "<li>Connectez-vous sur chacun. Si une case « Are you human » "
            "apparaît, cochez-la vous-même : c'est normal.</li>"
            "<li>Revenez ici et cliquez <b>Vérifier</b>.</li></ol>"
            "<p>Vous ne ferez cela qu'une fois : la fenêtre garde vos sessions. "
            "Laissez-la ouverte, ou réduite, quand une synchronisation doit "
            "avoir lieu.</p>"))
        row = QHBoxLayout()
        open_btn = QPushButton("Ouvrir les deux sites")
        open_btn.clicked.connect(self._open_sites)
        check = QPushButton("Vérifier")
        check.clicked.connect(self._check)
        row.addWidget(open_btn)
        row.addWidget(check)
        row.addStretch(1)
        self.box.addLayout(row)
        self.janitor = QLabel("Janitor : —")
        self.saucepan = QLabel("Saucepan : —")
        self.box.addWidget(self.janitor)
        self.box.addWidget(self.saucepan)
        self.box.addStretch(1)
        self.ok = False

    def _open_sites(self):
        self.run(sync.open_login_pages, self.wizard().settings, status=self.janitor,
                 done=lambda _: self.janitor.setText(
                     "Janitor : connectez-vous, puis « Vérifier »"))

    def _check(self):
        self.saucepan.setText("Saucepan : ⏳ …")

        def done(result):
            mark = {True: "✅ connecté", False: "❌ non connecté"}
            self.janitor.setText(f"Janitor : {mark[bool(result.get('janitor'))]}")
            self.saucepan.setText(f"Saucepan : {mark[bool(result.get('saucepan'))]}")
            self.ok = all(result.values())

        self.run(sync.check_sessions, self.wizard().settings,
                 done=done, status=self.janitor)

    def validatePage(self):
        if self.ok:
            return True
        answer = QMessageBox.question(
            self, "Naosnatcher",
            "Les connexions n'ont pas été vérifiées. Continuer quand même ?\n\n"
            "Les synchronisations échoueront tant que vous ne serez pas "
            "connecté aux deux sites dans la fenêtre pilotée.")
        return answer == QMessageBox.StandardButton.Yes


class AddressesPage(_Page):
    def __init__(self):
        super().__init__(
            "3. Les pages utilisées",
            "Les valeurs proposées conviennent dans presque tous les cas.")
        form = QFormLayout()
        self.janitor = QLineEdit()
        self.saucepan = QLineEdit()
        form.addRow("Liste de vos bots Janitor :", self.janitor)
        form.addRow("Éditeur Saucepan :", self.saucepan)
        self.box.addLayout(form)
        self.box.addWidget(_text(
            "<p><small>Ne les changez que si l'un des sites a modifié ses "
            "adresses.</small></p>"))
        self.box.addStretch(1)

    def initializePage(self):
        s = self.wizard().settings
        self.janitor.setText(s.get("janitor_list_url") or config.JANITOR_MY_CHARACTERS)
        self.saucepan.setText(s.get("saucepan_new_url") or DEFAULT_SAUCEPAN_EDITOR)


class KnownBotsPage(_Page):
    def __init__(self):
        super().__init__("4. Vos bots déjà publiés")
        self.info = _text("")
        self.box.addWidget(self.info)
        self.seed = QRadioButton(
            "Les ignorer : seuls les bots créés à partir d'aujourd'hui seront "
            "envoyés (recommandé)")
        self.send = QRadioButton(
            "Les envoyer aussi, petit à petit (quelques-uns par jour)")
        self.keep = QRadioButton("Garder le registre importé tel quel")
        for b in (self.seed, self.send, self.keep):
            self.box.addWidget(b)
        self.box.addStretch(1)

    def initializePage(self):
        known = len(state.load_seen())
        self.keep.setVisible(bool(known))
        if known:
            self.info.setText(
                f"<p>{known} bot(s) figurent déjà au registre importé. Les "
                "garder évite de renvoyer ce qui l'a déjà été.</p>")
            self.keep.setChecked(True)
        else:
            self.info.setText(
                "<p>Votre compte Janitor contient sans doute déjà des bots. "
                "Que faut-il en faire ?</p>")
            self.seed.setChecked(True)


class SchedulePage(_Page):
    def __init__(self):
        super().__init__("5. La synchronisation quotidienne")
        row = QHBoxLayout()
        row.addWidget(QLabel("Chaque jour à"))
        self.hour = QSpinBox()
        self.hour.setRange(0, 23)
        self.minute = QSpinBox()
        self.minute.setRange(0, 59)
        row.addWidget(self.hour)
        row.addWidget(QLabel("h"))
        row.addWidget(self.minute)
        row.addStretch(1)
        self.box.addLayout(row)

        self.system = QCheckBox(
            "Lancer la synchronisation même quand Naosnatcher est fermé (recommandé)")
        self.system.setToolTip(
            "Confie l'horaire au système (Planificateur de tâches sous Windows). "
            "Si le PC est éteint à l'heure prévue, la synchronisation a lieu "
            "au démarrage suivant.")
        self.box.addWidget(self.system)

        self.limit = QSpinBox()
        self.limit.setRange(1, 20)
        row = QHBoxLayout()
        row.addWidget(QLabel("Bots envoyés au plus par jour :"))
        row.addWidget(self.limit)
        row.addStretch(1)
        self.box.addLayout(row)

        self.cards = QCheckBox(
            "Créer aussi la carte de personnage (PNG) de chaque bot synchronisé")
        self.box.addWidget(self.cards)
        self.box.addStretch(1)

    def initializePage(self):
        s = self.wizard().settings
        self.hour.setValue(int(s.get("daily_hour", config.DAILY_HOUR)))
        self.minute.setValue(int(s.get("daily_minute", config.DAILY_MINUTE)))
        self.limit.setValue(int(s.get("daily_limit") or 2))
        self.cards.setChecked(bool(s.get("make_cards")))
        self.system.setChecked(True)


class DonePage(_Page):
    def __init__(self):
        super().__init__("C'est prêt")
        self.summary = _text("")
        self.box.addWidget(self.summary)
        self.dry_run = QCheckBox(
            "Faire une simulation tout de suite (rien n'est publié)")
        self.dry_run.setChecked(True)
        self.box.addWidget(self.dry_run)
        self.box.addStretch(1)

    def initializePage(self):
        w = self.wizard()
        p = w.pages
        when = f"{p['schedule'].hour.value():02d}:{p['schedule'].minute.value():02d}"
        self.summary.setText(
            f"<p>Synchronisation chaque jour à <b>{when}</b>"
            + (", fenêtre ouverte ou non" if p["schedule"].system.isChecked()
               else ", tant que Naosnatcher est ouvert") + ".</p>"
            "<p>La simulation va jusqu'au collage de la fiche dans Saucepan, "
            "puis s'arrête : c'est le moyen de tout vérifier sans risque. Le "
            "déroulé s'affiche dans l'onglet Journal.</p>"
            f"<p>Vos données sont dans <code>{config.ROOT}</code>.</p>")


class SetupWizard(QWizard):
    """Renvoie, après `exec()`, l'action à enchaîner : 'seed', 'dry_run' ou None."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Naosnatcher — configuration")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setButtonText(QWizard.WizardButton.NextButton, "Suivant >")
        self.setButtonText(QWizard.WizardButton.BackButton, "< Précédent")
        self.setButtonText(QWizard.WizardButton.FinishButton, "Terminer")
        self.setButtonText(QWizard.WizardButton.CancelButton, "Annuler")
        self.resize(720, 540)
        self._jobs = []
        self.followup = []
        self.reload_settings()

        self.pages = {
            "welcome": WelcomePage(), "browser": BrowserPage(),
            "login": LoginPage(), "addresses": AddressesPage(),
            "known": KnownBotsPage(), "schedule": SchedulePage(),
            "done": DonePage(),
        }
        for page in self.pages.values():
            self.addPage(page)

    def reload_settings(self):
        self.settings = state.load_settings()

    def accept(self):
        p = self.pages
        s = state.load_settings()
        s.update({
            "janitor_list_url": state.clean_url(p["addresses"].janitor.text()),
            "saucepan_new_url": state.clean_url(p["addresses"].saucepan.text()),
            "daily_hour": p["schedule"].hour.value(),
            "daily_minute": p["schedule"].minute.value(),
            "daily_limit": p["schedule"].limit.value(),
            "make_cards": p["schedule"].cards.isChecked(),
            "enabled": True,
            "setup_done": True,
        })
        state.save_settings(s)

        if p["schedule"].system.isChecked():
            try:
                schedule.install(s["daily_hour"], s["daily_minute"])
            except Exception as exc:                               # noqa: BLE001
                QMessageBox.warning(
                    self, "Naosnatcher",
                    "La tâche planifiée n'a pas pu être créée :\n"
                    f"{exc}\n\nLa synchronisation aura lieu tant que "
                    "Naosnatcher reste ouvert.")

        if p["known"].seed.isChecked():
            self.followup.append("seed")
        if p["done"].dry_run.isChecked():
            self.followup.append("dry_run")
        super().accept()


def needs_setup(settings):
    """Premier lancement : ni assistant mené à terme, ni configuration existante."""
    return not settings.get("setup_done") and not settings.get("janitor_list_url")

