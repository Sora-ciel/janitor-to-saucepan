"""Fenêtre de contrôle : configuration, exécution, journal, planification.

Le navigateur n'est plus intégré à l'application : c'est le vôtre, piloté à
distance (voir driver.py). Cette fenêtre ne sert donc qu'à configurer, lancer
et suivre les synchronisations.
"""

import os
import sys
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, QThread, QUrl
from PyQt6.QtGui import QDesktopServices, QIcon
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from . import card_editor, config, driver, location, schedule, state, sync, wizard
from .worker import Worker

# Délai avant de retenter un cycle planifié qui a échoué.
RETRY_DELAY = timedelta(hours=1)


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Naosnatcher — Janitor ➜ Saucepan")
        self.resize(920, 700)

        self.settings = state.load_settings()
        self._thread = None
        self._worker = None
        # Dernière tentative planifiée, réussie ou non (voir `_tick`).
        self._last_attempt = None

        tabs = QTabWidget()
        tabs.addTab(self._config_tab(), "Configuration")
        tabs.addTab(self._send_tab(), "Envoyer un bot")
        tabs.addTab(self._cards_tab(), "Cartes de personnage")
        tabs.addTab(card_editor.CardEditor(self), "Créer une carte")
        tabs.addTab(self._log_tab(), "Journal")
        self.tabs = tabs
        # Actions à enchaîner après l'assistant (marquage, puis simulation).
        self._followup = []
        self.setCentralWidget(tabs)

        for line in state.tail_log(200):
            self.log_view.appendPlainText(line)

        self._start_scheduler()

    # ── Onglets ─────────────────────────────────────────────────────────────

    def _config_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        top = QHBoxLayout()
        top.addWidget(QLabel("Première utilisation, ou un doute ?"))
        wiz_btn = QPushButton("Assistant de configuration…")
        wiz_btn.clicked.connect(self.open_wizard)
        top.addWidget(wiz_btn)
        top.addStretch(1)
        layout.addLayout(top)

        # -- Navigateur ------------------------------------------------------
        nav = QGroupBox("1. Navigateur")
        nl = QVBoxLayout(nav)
        nl.addWidget(QLabel(
            "Naosnatcher pilote votre propre navigateur. Ouvrez-le ici, "
            "connectez-vous à Janitor et à Saucepan — contrôle Cloudflare "
            "compris — puis laissez la fenêtre ouverte."
        ))
        row = QHBoxLayout()
        open_btn = QPushButton("Ouvrir le navigateur piloté")
        open_btn.clicked.connect(self._open_browser)
        check_btn = QPushButton("Vérifier la connexion")
        check_btn.clicked.connect(self._check_browser)
        self.browser_status = QLabel("—")
        row.addWidget(open_btn); row.addWidget(check_btn)
        row.addWidget(self.browser_status, 1)
        nl.addLayout(row)
        layout.addWidget(nav)

        # -- URLs ------------------------------------------------------------
        urls = QGroupBox("2. Pages à utiliser")
        ul = QVBoxLayout(urls)
        ul.addWidget(QLabel(
            "Collez l'adresse de votre liste de bots Janitor, et celle de "
            "l'éditeur de nouvelle companion Saucepan."
        ))
        self.janitor_url_field = QLineEdit(self.settings.get("janitor_list_url", ""))
        self.saucepan_url_field = QLineEdit(self.settings.get("saucepan_new_url", ""))
        for label, field, key in (
            ("Liste de mes bots Janitor", self.janitor_url_field, "janitor_list_url"),
            ("Éditeur Saucepan", self.saucepan_url_field, "saucepan_new_url"),
        ):
            r = QHBoxLayout()
            r.addWidget(QLabel(label), 2)
            r.addWidget(field, 6)
            field.editingFinished.connect(
                lambda f=field, k=key: self._save(k, f.text().strip()))
            if field is self.janitor_url_field:
                # Verrouillée : une adresse fausse ferait échouer chaque cycle.
                field.setReadOnly(True)
                self.list_lock = QPushButton("🔒")
                self.list_lock.setCheckable(True)
                self.list_lock.setToolTip("Déverrouiller pour modifier l'adresse")
                self.list_lock.toggled.connect(self._toggle_list_lock)
                r.addWidget(self.list_lock)
            ul.addLayout(r)
        layout.addWidget(urls)

        # -- Planification ---------------------------------------------------
        sched = QGroupBox("3. Synchronisation quotidienne")
        sl = QHBoxLayout(sched)
        self.enabled_box = QCheckBox("Activée")
        self.enabled_box.setChecked(bool(self.settings.get("enabled", True)))
        self.enabled_box.stateChanged.connect(
            lambda: self._save("enabled", self.enabled_box.isChecked()))

        self.hour_spin = QSpinBox(); self.hour_spin.setRange(0, 23)
        self.hour_spin.setValue(int(self.settings.get("daily_hour", 8)))
        self.hour_spin.valueChanged.connect(
            lambda v: (self._save("daily_hour", v), self._update_next_run_label()))

        self.minute_spin = QSpinBox(); self.minute_spin.setRange(0, 59)
        self.minute_spin.setValue(int(self.settings.get("daily_minute", 0)))
        self.minute_spin.valueChanged.connect(
            lambda v: (self._save("daily_minute", v), self._update_next_run_label()))

        self.catchup_box = QCheckBox("Rattraper les exécutions manquées")
        self.catchup_box.setToolTip(
            "Si le PC était éteint à l'heure prévue, lancer la synchronisation "
            "au démarrage suivant."
        )
        self.catchup_box.setChecked(bool(self.settings.get("catch_up", True)))
        self.catchup_box.stateChanged.connect(
            lambda: self._save("catch_up", self.catchup_box.isChecked()))

        sl.addWidget(self.enabled_box)
        sl.addWidget(QLabel("Heure :")); sl.addWidget(self.hour_spin)
        sl.addWidget(QLabel("Minute :")); sl.addWidget(self.minute_spin)
        sl.addWidget(self.catchup_box)
        sl.addStretch(1)
        self.system_box = QCheckBox("Même fenêtre fermée")
        self.system_box.setToolTip(
            "Confie l'horaire au système (Planificateur de tâches sous "
            "Windows, minuteur systemd sous Linux).")
        self.system_box.setChecked(schedule.is_installed())
        self.system_box.toggled.connect(self._toggle_system_schedule)
        for spin in (self.hour_spin, self.minute_spin):
            spin.editingFinished.connect(self._refresh_system_schedule)
        sl.addWidget(self.system_box)
        self.next_run_label = QLabel("—")
        sl.addWidget(self.next_run_label)
        layout.addWidget(sched)

        # -- Actions ---------------------------------------------------------
        actions = QGroupBox("4. Actions")
        al = QVBoxLayout(actions)

        top = QHBoxLayout()
        self.dry_btn = QPushButton("Simulation (ne modifie rien)")
        self.dry_btn.setToolTip(
            "Va jusqu'au collage du JSON dans Saucepan puis s'arrête. "
            "Ni restauration, ni enregistrement, ni publication."
        )
        self.dry_btn.clicked.connect(lambda: self.run_sync(dry_run=True))

        self.run_btn = QPushButton("Synchroniser maintenant")
        self.run_btn.clicked.connect(lambda: self.run_sync())
        top.addWidget(self.dry_btn); top.addWidget(self.run_btn)
        al.addLayout(top)

        self.seed_btn = QPushButton("Marquer les bots actuels comme déjà connus")
        self.seed_btn.setToolTip(
            "À faire une fois, au début : enregistre les bots existants sans "
            "les envoyer, pour que seuls les futurs ajouts soient synchronisés."
        )
        self.seed_btn.clicked.connect(self._seed)
        al.addWidget(self.seed_btn)
        layout.addWidget(actions)

        # -- Emplacement des donnees ----------------------------------------
        place = QGroupBox("5. Emplacement des donnees")
        pl = QVBoxLayout(place)
        _note = QLabel(
            "Registre, reglages, journal et exports. Un dossier visible "
            "depuis Windows et depuis Linux permet aux deux systemes de "
            "partager le meme registre, donc de ne jamais renvoyer deux fois "
            "le meme bot. Le profil du navigateur, lui, reste propre a chaque "
            "systeme.")
        _note.setWordWrap(True)
        pl.addWidget(_note)
        self.place_label = QLabel(location.describe_current())
        self.place_label.setWordWrap(True)
        pl.addWidget(self.place_label)
        place_btn = QPushButton("Changer l'emplacement des donnees…")
        place_btn.clicked.connect(self._change_location)
        pl.addWidget(place_btn)
        layout.addWidget(place)

        layout.addStretch(1)
        return w

    def _toggle_list_lock(self, unlocked):
        self.janitor_url_field.setReadOnly(not unlocked)
        self.list_lock.setText("🔓" if unlocked else "🔒")
        if not unlocked:
            self._save("janitor_list_url", self.janitor_url_field.text().strip())

    def _send_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel(
            "Collez l'adresse d'un bot Janitor — n'importe lequel — pour l'envoyer "
            "sur Saucepan tout de suite.\nAucune règle de la synchronisation "
            "automatique ne s'applique : saisons écartées, bots privés, plafond "
            "du jour, bot déjà envoyé."))
        self.send_urls = QPlainTextEdit()
        self.send_urls.setPlaceholderText(
            "https://janitorai.com/characters/…\n(une adresse par ligne)")
        layout.addWidget(self.send_urls)
        row = QHBoxLayout()
        self.send_dry_btn = QPushButton("Simulation (ne modifie rien)")
        self.send_dry_btn.clicked.connect(lambda: self._send_urls(dry_run=True))
        self.send_btn = QPushButton("Envoyer sur Saucepan")
        self.send_btn.clicked.connect(lambda: self._send_urls())
        row.addWidget(self.send_dry_btn)
        row.addWidget(self.send_btn)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        return w

    def _send_urls(self, dry_run=False):
        urls = [u.strip() for u in self.send_urls.toPlainText().splitlines() if u.strip()]
        if not urls:
            QMessageBox.information(self, "Naosnatcher",
                                    "Collez d'abord l'adresse d'un bot Janitor.")
            return
        if self._busy():
            self.log("Une tâche est déjà en cours — demande ignorée.")
            return
        self.settings = state.load_settings()
        self.log(f"═══ Envoi à la demande ({len(urls)})"
                 + (" — simulation" if dry_run else ""))
        self.tabs.setCurrentIndex(self.tabs.count() - 1)
        self._start(sync.sync_urls, self.settings, urls=urls, dry_run=dry_run,
                    on_finished=self._on_send_finished)

    def _on_send_finished(self, result):
        # Pas de `last_run` ici : un envoi manuel ne remplace pas le cycle du jour.
        self._cleanup_thread()
        r = result or {}
        self.log(f"✅ Envoi terminé : {r.get('ok', 0)} réussi(s), "
                 f"{r.get('skipped', 0)} simulé(s), {r.get('failed', 0)} échec(s).")
        self._fill_card_list()

    def _cards_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel(
            "Une carte de personnage est l'avatar du bot, en PNG, avec sa fiche "
            "complète intégrée. Janitor, SillyTavern, Chub… savent l'importer."))

        by_url = QGroupBox("Depuis l'adresse d'un bot Janitor (le vôtre ou non)")
        ul = QVBoxLayout(by_url)
        self.card_urls = QPlainTextEdit()
        self.card_urls.setPlaceholderText(
            "https://janitorai.com/characters/…\n(une adresse par ligne)")
        self.card_urls.setMaximumHeight(90)
        ul.addWidget(self.card_urls)
        self.card_url_btn = QPushButton("Créer la ou les cartes")
        self.card_url_btn.clicked.connect(self._cards_from_urls)
        ul.addWidget(self.card_url_btn, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(by_url)

        synced = QGroupBox("Depuis vos bots synchronisés")
        sl = QVBoxLayout(synced)
        self.card_list = QListWidget()
        sl.addWidget(self.card_list)
        row = QHBoxLayout()
        for label, slot in (("Tout cocher", lambda: self._check_all(True)),
                            ("Tout décocher", lambda: self._check_all(False)),
                            ("Rafraîchir", self._fill_card_list)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        self.card_list_btn = QPushButton("Créer les cartes cochées")
        self.card_list_btn.clicked.connect(self._cards_from_list)
        row.addWidget(self.card_list_btn)
        sl.addLayout(row)
        layout.addWidget(synced, 1)

        bottom = QHBoxLayout()
        self.auto_cards = QCheckBox(
            "Créer automatiquement la carte de chaque nouveau bot synchronisé")
        self.auto_cards.setChecked(bool(self.settings.get("make_cards")))
        self.auto_cards.toggled.connect(lambda v: self._save("make_cards", v))
        bottom.addWidget(self.auto_cards)
        bottom.addStretch(1)
        folder = QPushButton("Ouvrir le dossier des cartes")
        folder.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(config.CARDS_DIR)))
        bottom.addWidget(folder)
        layout.addLayout(bottom)

        self._fill_card_list()
        return w

    def _fill_card_list(self):
        self.card_list.clear()
        entries = [(cid, e) for cid, e in state.load_seen().items()
                   if e.get("status") in ("ok", "created") and e.get("name")]
        entries.sort(key=lambda item: item[1].get("synced_at") or "", reverse=True)
        for cid, entry in entries:
            when = (entry.get("synced_at") or "")[:10]
            item = QListWidgetItem(f"{entry['name']}    ·  {when}    ·  {cid[:8]}")
            item.setData(Qt.ItemDataRole.UserRole, cid)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.card_list.addItem(item)

    def _check_all(self, checked):
        state_ = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.card_list.count()):
            self.card_list.item(i).setCheckState(state_)

    def _cards_from_urls(self):
        urls = [u.strip() for u in self.card_urls.toPlainText().splitlines() if u.strip()]
        if not urls:
            QMessageBox.information(self, "Naosnatcher",
                                    "Collez d'abord l'adresse d'un bot Janitor.")
            return
        self._run_cards(urls=urls)

    def _cards_from_list(self):
        ids = [self.card_list.item(i).data(Qt.ItemDataRole.UserRole)
               for i in range(self.card_list.count())
               if self.card_list.item(i).checkState() == Qt.CheckState.Checked]
        if not ids:
            QMessageBox.information(self, "Naosnatcher", "Cochez au moins un bot.")
            return
        self._run_cards(char_ids=ids)

    def _run_cards(self, char_ids=(), urls=()):
        if self._busy():
            self.log("Une tâche est déjà en cours — demande ignorée.")
            return
        self.settings = state.load_settings()
        self.log(f"═══ Cartes de personnage ({len(char_ids) + len(urls)})")
        self.tabs.setCurrentIndex(self.tabs.count() - 1)
        self._start(sync.make_cards, self.settings,
                    char_ids=list(char_ids), urls=list(urls),
                    on_finished=self._on_cards_finished)

    def _on_cards_finished(self, written):
        self._cleanup_thread()
        written = written or []
        self.log(f"✅ {len(written)} carte(s) créée(s).")
        if written:
            QDesktopServices.openUrl(QUrl.fromLocalFile(config.CARDS_DIR))

    # ── Assistant et planification système ─────────────────────────────────

    def open_wizard(self):
        wiz = wizard.SetupWizard(self)
        if not wiz.exec():
            return
        self.settings = state.load_settings()
        self.janitor_url_field.setText(self.settings.get("janitor_list_url", ""))
        self.saucepan_url_field.setText(self.settings.get("saucepan_new_url", ""))
        self.hour_spin.setValue(int(self.settings.get("daily_hour", 8)))
        self.minute_spin.setValue(int(self.settings.get("daily_minute", 0)))
        self.auto_cards.setChecked(bool(self.settings.get("make_cards")))
        self.system_box.blockSignals(True)
        self.system_box.setChecked(schedule.is_installed())
        self.system_box.blockSignals(False)
        self._update_next_run_label()
        self._fill_card_list()
        self._followup = list(wiz.followup)
        self._next_followup()

    def _next_followup(self):
        if not self._followup or self._busy():
            return
        step = self._followup.pop(0)
        self.tabs.setCurrentIndex(self.tabs.count() - 1)
        if step == "seed":
            self.run_sync(seed=True)
        elif step == "dry_run":
            self.run_sync(dry_run=True)

    def _toggle_system_schedule(self, on):
        try:
            if on:
                schedule.install(self.hour_spin.value(), self.minute_spin.value())
                self.log("Synchronisation quotidienne confiée au système.")
            else:
                schedule.uninstall()
                self.log("Tâche planifiée du système retirée.")
        except Exception as exc:                                   # noqa: BLE001
            QMessageBox.warning(self, "Naosnatcher", f"Planification : {exc}")
            self.system_box.blockSignals(True)
            self.system_box.setChecked(not on)
            self.system_box.blockSignals(False)

    def _refresh_system_schedule(self):
        """Nouvel horaire : la tâche du système suit."""
        if self.system_box.isChecked():
            self._toggle_system_schedule(True)

    def _log_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        layout.addWidget(self.log_view)
        return w

    # ── Navigateur ──────────────────────────────────────────────────────────

    def _open_browser(self):
        try:
            info = driver.ensure_browser(self.settings.get("browser_path"))
            name = info.get("Browser", "navigateur")
            self.browser_status.setText(f"✅ {name}")
            self.log(f"Navigateur prêt : {name}")
            QMessageBox.information(
                self, "Naosnatcher",
                "Le navigateur piloté est ouvert.\n\n"
                "Connectez-vous à Janitor et à Saucepan dans cette fenêtre "
                "(le contrôle « are you human » se passe normalement, c'est "
                "vous qui le faites).\n\n"
                "Ensuite, laissez-la ouverte."
            )
        except Exception as exc:                                   # noqa: BLE001
            self.browser_status.setText("❌ indisponible")
            self.log(f"Navigateur : {exc}")
            QMessageBox.warning(self, "Naosnatcher", str(exc))

    def _check_browser(self):
        info = driver.is_cdp_up()
        if info:
            self.browser_status.setText(f"✅ {info.get('Browser', 'connecté')}")
            self.log(f"Navigateur joignable : {info.get('Browser')}")
        else:
            self.browser_status.setText("❌ non joignable")
            self.log("Navigateur non joignable — utilisez « Ouvrir le navigateur piloté ».")

    # ── Exécution ───────────────────────────────────────────────────────────

    def _save(self, key, value):
        self.settings = state.set_setting(key, value)

    def _change_location(self):
        """Choisit un autre dossier de donnees, puis invite a redemarrer.

        Les chemins sont figes a l'import de `config` : appliquer le changement
        a chaud laisserait une partie de l'application sur l'ancien dossier.
        """
        chosen = location.ask_and_apply(self, config.ROOT)
        if not chosen:
            return
        self.place_label.setText(location.describe_current())
        if os.path.abspath(chosen) == os.path.abspath(config.ROOT):
            QMessageBox.information(
                self, "Naosnatcher", "C'est deja l'emplacement utilise.")
            return
        QMessageBox.information(
            self, "Naosnatcher",
            "Emplacement enregistre :" + chr(10) + chosen + chr(10) * 2
            + "Fermez puis relancez Naosnatcher pour qu'il y travaille.")

    def _display(self, line):
        """Affiche une ligne déjà consignée au journal."""
        self.log_view.appendPlainText(line)
        bar = self.log_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def log(self, message):
        self._display(state.log(message))

    def _busy(self):
        return self._thread is not None and self._thread.isRunning()

    def _set_running(self, running):
        for b in (self.run_btn, self.dry_btn, self.seed_btn,
                  self.send_btn, self.send_dry_btn,
                  self.card_url_btn, self.card_list_btn):
            b.setEnabled(not running)

    def run_sync(self, seed=False, dry_run=False, scheduled=False):
        if self._busy():
            self.log("Synchronisation déjà en cours — demande ignorée.")
            return

        self.settings = state.load_settings()
        kind = "simulation" if dry_run else ("planifiée" if scheduled else "manuelle")
        self.log(f"═══ Synchronisation {kind}")
        self._set_running(True)

        self._start(sync.full_sync, self.settings, first_run_seed=seed,
                    dry_run=dry_run, on_finished=self._on_finished)

    def _start(self, fn, *args, on_finished, **kwargs):
        """Lance `fn(…, log=…)` hors du fil de l'interface."""
        self._set_running(True)
        self._thread = QThread(self)
        self._worker = Worker(fn, *args, **kwargs)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        # Les tâches écrivent déjà au journal : ici on ne fait qu'afficher,
        # sans quoi chaque ligne y figurerait deux fois.
        self._worker.message.connect(self._display)
        self._worker.finished.connect(on_finished)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

    def _cleanup_thread(self):
        self._set_running(False)
        if self._thread:
            self._thread.quit()
            self._thread.wait(3000)
        self._thread = None
        self._worker = None

    def _on_finished(self, result):
        self._cleanup_thread()
        if isinstance(result, dict):
            if result.get("seeded"):
                self.log(f"✅ {result['seeded']} bot(s) enregistrés comme connus.")
            elif result.get("dry_run"):
                self.log(f"✅ Simulation : {result.get('skipped', 0)} bot(s) prêts, "
                         f"{result.get('failed', 0)} problème(s). Rien n'a été modifié.")
            else:
                self.log(f"✅ Fin : {result.get('ok', 0)} réussi(s), "
                         f"{result.get('failed', 0)} échec(s).")
                # On ne note la date que sur un vrai cycle : une simulation ne
                # doit pas faire sauter le rattrapage du lendemain.
                self._save("last_run", datetime.now().isoformat(timespec="seconds"))
        self._update_next_run_label()
        self._fill_card_list()
        self._next_followup()

    def _on_failed(self, message):
        self._cleanup_thread()
        self._followup = []
        self.log(f"❌ Interrompu : {message}")

    def _seed(self):
        answer = QMessageBox.question(
            self, "Naosnatcher",
            "Enregistrer tous les bots actuellement sur votre compte Janitor "
            "comme « déjà connus », sans rien envoyer sur Saucepan ?\n\n"
            "Seuls les bots ajoutés après cette opération seront synchronisés.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.run_sync(seed=True)

    # ── Planification ───────────────────────────────────────────────────────

    def _scheduled_time_today(self):
        return datetime.now().replace(
            hour=int(self.settings.get("daily_hour", 8)),
            minute=int(self.settings.get("daily_minute", 0)),
            second=0, microsecond=0,
        )

    def _next_run_at(self):
        target = self._scheduled_time_today()
        if target <= datetime.now():
            target += timedelta(days=1)
        return target

    def _last_run(self):
        raw = self.settings.get("last_run")
        try:
            return datetime.fromisoformat(raw) if raw else None
        except ValueError:
            return None

    def _missed_run(self):
        """L'heure prévue est-elle passée aujourd'hui sans exécution ?

        Sans ça, un PC éteint à 8 h ferait simplement sauter la journée.
        """
        if not self.settings.get("catch_up", True):
            return False
        due = self._scheduled_time_today()
        if datetime.now() < due:
            return False
        last = self._last_run()
        return last is None or last < due

    def _start_scheduler(self):
        from PyQt6.QtCore import QTimer
        self._sched_timer = QTimer(self)
        self._sched_timer.timeout.connect(self._tick)
        self._sched_timer.start(30_000)
        self._update_next_run_label()

        if self._configured() and self.settings.get("enabled", True) \
                and self._missed_run():
            self.log("Exécution manquée détectée — rattrapage.")
            self._last_attempt = datetime.now()
            self.run_sync(scheduled=True)

    def _update_next_run_label(self):
        self.next_run_label.setText(
            f"Prochaine exécution : {self._next_run_at():%d/%m %H:%M}")

    def _configured(self):
        """Rien à planifier tant que l'assistant n'a pas fourni les adresses."""
        return bool(self.settings.get("janitor_list_url")
                    and self.settings.get("saucepan_new_url"))

    def _tick(self):
        if not self.settings.get("enabled", True) or self._busy() \
                or not self._configured():
            return
        due = self._scheduled_time_today()
        # Un cycle en échec ne pose pas `last_run` : sans ce délai, on
        # relancerait toutes les 30 s — et une session Janitor expirée
        # martèlerait le site jusqu'à ce que quelqu'un se reconnecte.
        if self._last_attempt and datetime.now() - self._last_attempt < RETRY_DELAY:
            return
        # Relu à chaque fois : le minuteur système a pu faire le cycle du jour.
        self.settings = state.load_settings()
        last = self._last_run()
        if datetime.now() >= due and (last is None or last < due):
            self._last_attempt = datetime.now()
            self.run_sync(scheduled=True)
            self._update_next_run_label()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Naosnatcher")
    app.setWindowIcon(QIcon(config.ICON_FILE))

    # Naosnatcher.exe lancé depuis Téléchargements : proposer de s'installer.
    from . import install
    if install.should_offer_install():
        verb = "Mettre à jour" if install.is_installed() else "Installer"
        answer = QMessageBox.question(
            None, "Naosnatcher",
            f"{verb} Naosnatcher sur ce PC ?\n\n"
            f"Le programme sera copié dans {install.install_dir()}, avec un "
            "raccourci dans le menu Démarrer et sur le bureau. Aucun droit "
            "administrateur n'est demandé.\n\n"
            "« Non » : l'utiliser sans l'installer.")
        if answer == QMessageBox.StandardButton.Yes:
            # Ou ranger les donnees ? Pose la question **avant** d'installer :
            # le repere doit etre ecrit avant que la copie installee demarre,
            # sinon elle partirait sur l'emplacement par defaut et croirait
            # n'avoir jamais rien synchronise.
            #
            # Pre-rempli avec l'emplacement **actuel**, pas le defaut : lors
            # d'une mise a jour, un simple « OK » doit garder le dossier en
            # place. Pre-remplir le defaut faisait basculer sur un registre
            # vide, et la synchro suivante renvoyait tout l'historique.
            # (Premiere installation : l'emplacement actuel EST le defaut.)
            location.ask_and_apply(None, config.ROOT)
            try:
                install.install()
            except OSError as exc:
                QMessageBox.warning(
                    None, "Naosnatcher",
                    f"Installation impossible : {exc}\n\nSi Naosnatcher est "
                    "déjà ouvert, fermez-le puis réessayez.")
            else:
                install.launch_installed()
                return 0
    window = MainWindow()
    window.show()
    if wizard.needs_setup(window.settings):
        window.open_wizard()
    return app.exec()


if __name__ == "__main__":
    main()
