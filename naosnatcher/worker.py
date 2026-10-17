"""Exécution d'une tâche longue hors du fil de l'interface.

L'API Playwright utilisée est bloquante ; la faire tourner dans le fil
principal figerait la fenêtre pendant toute la durée de la tâche.
"""

from PyQt6.QtCore import QObject, QThread, pyqtSignal


class Worker(QObject):
    """Appelle `fn(*args, log=…, **kwargs)` dans un fil à part.

    `log` est relié au signal `message`, que l'interface affiche.
    """

    message = pyqtSignal(str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs

    def run(self):
        try:
            self.finished.emit(self.fn(*self.args, log=self.message.emit, **self.kwargs))
        except Exception as exc:                                   # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")


def start(parent, fn, *args, on_message=None, on_finished=None, on_failed=None,
          **kwargs):
    """Lance `fn` dans un fil ; renvoie (thread, worker) à garder en vie."""
    thread = QThread(parent)
    worker = Worker(fn, *args, **kwargs)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    if on_message:
        worker.message.connect(on_message)
    for signal, slot in ((worker.finished, on_finished), (worker.failed, on_failed)):
        if slot:
            signal.connect(slot)
        signal.connect(thread.quit)
    thread.start()
    return thread, worker
