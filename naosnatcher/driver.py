"""Pilotage du vrai navigateur de l'utilisateur, via Playwright et CDP.

Pourquoi ce détour plutôt qu'un navigateur intégré : Cloudflare rejette
l'environnement QtWebEngine, et la case « are you human » passe au rouge quoi
qu'on fasse. On ne cherche pas à tromper ce contrôle. On l'évite en le rendant
inutile : **c'est vous qui vous connectez, dans votre propre Vivaldi, et qui
passez le contrôle en tant qu'humain.** L'automatisation se contente ensuite de
réutiliser la session qui en résulte.

Concrètement, Vivaldi doit être démarré avec le port de débogage ouvert :

    vivaldi.exe --remote-debugging-port=9222

`ensure_browser()` s'en charge, et `Driver` s'y raccroche.
"""

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

from . import config

CDP_PORT = 9222
CDP_ENDPOINT = f"http://127.0.0.1:{CDP_PORT}"

# Emplacements habituels de Vivaldi sous Windows, puis repli sur Chrome/Edge :
# n'importe quel navigateur Chromium fait l'affaire, l'essentiel est que ce
# soit *celui où vous êtes connecté*.
if sys.platform == "win32":
    BROWSER_CANDIDATES = [
        os.path.expandvars(r"%LOCALAPPDATA%\Vivaldi\Application\vivaldi.exe"),
        r"C:\Program Files\Vivaldi\Application\vivaldi.exe",
        r"C:\Program Files (x86)\Vivaldi\Application\vivaldi.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    BROWSER_NAMES = ("vivaldi", "chrome", "msedge")
else:
    # Sous Linux, les navigateurs sont dans le PATH.
    BROWSER_CANDIDATES = []
    BROWSER_NAMES = ("vivaldi", "vivaldi-stable", "google-chrome",
                     "google-chrome-stable", "chromium", "chromium-browser",
                     "brave-browser", "microsoft-edge")


class DriverError(RuntimeError):
    pass


# ── Découverte et démarrage du navigateur ───────────────────────────────────

def find_browser():
    """Chemin du navigateur à piloter, ou None."""
    for path in BROWSER_CANDIDATES:
        if path and os.path.isfile(path):
            return path
    for name in BROWSER_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return None


def profile_dir(browser_path):
    """Dossier du profil dédié au navigateur piloté.

    Sous Windows, il vit dans le projet. Sous Linux, il est rangé à part : les
    cookies d'un profil Windows sont chiffrés par le système et illisibles
    ailleurs, il faut donc de toute façon s'y reconnecter une fois. Et un
    navigateur installé en snap n'a pas accès au disque monté du projet, ni
    aux dossiers cachés du répertoire personnel — d'où `~/snap/<nom>/common`.
    """
    if sys.platform == "win32":
        return os.path.join(config.BROWSER_STATE, "cdp_profile")
    real = os.path.realpath(browser_path)
    if real.startswith("/snap/") or browser_path.startswith("/snap/"):
        snap = os.path.basename(browser_path)
        return os.path.expanduser(f"~/snap/{snap}/common/naosnatcher-profile")
    return os.path.expanduser("~/.local/share/naosnatcher/cdp_profile")


def is_cdp_up(timeout=1.5):
    """Le port de débogage répond-il ?"""
    try:
        with urllib.request.urlopen(f"{CDP_ENDPOINT}/json/version", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def launch_browser(browser_path=None, wait=20):
    """Démarre le navigateur avec le port de débogage ouvert.

    Un profil dédié est utilisé (`browser_state/cdp_profile`) : Chromium refuse
    d'ouvrir le port de débogage sur un profil déjà ouvert ailleurs, et on évite
    ainsi d'exiger que vous fermiez vos fenêtres en cours.

    Conséquence à connaître : ce profil démarre vierge. Vous vous y connectez
    une fois à Janitor et à Saucepan — contrôle Cloudflare inclus — et la
    session y reste ensuite.
    """
    existing = is_cdp_up()
    if existing:
        return existing

    # Un chemin réglé sous l'autre système (C:\… vu depuis Linux) ne mène
    # nulle part : on retombe alors sur la détection automatique.
    path = browser_path if browser_path and os.path.isfile(browser_path) \
        else find_browser()
    if not path:
        raise DriverError(
            "Aucun navigateur Chromium trouvé (Vivaldi, Chrome, Edge). "
            "Indiquez son chemin dans data/settings.json (clé browser_path)."
        )

    profile = profile_dir(path)
    os.makedirs(profile, exist_ok=True)

    subprocess.Popen(
        [path,
         f"--remote-debugging-port={CDP_PORT}",
         f"--user-data-dir={profile}",
         "--no-first-run",
         "--no-default-browser-check"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.time() + wait
    while time.time() < deadline:
        info = is_cdp_up()
        if info:
            return info
        time.sleep(0.5)

    raise DriverError(
        f"Le navigateur n'a pas ouvert son port de débogage en {wait}s. "
        "Fermez toutes ses fenêtres et réessayez."
    )


def ensure_browser(browser_path=None):
    """Garantit qu'un navigateur pilotable est disponible."""
    return is_cdp_up() or launch_browser(browser_path)


# ── Aides JavaScript, validées sur le DOM réel de Saucepan ──────────────────

JS_HELPERS = r"""
() => {
  window.__naos = {
    buttonByText(text) {
      const want = text.trim().toLowerCase();
      return [...document.querySelectorAll('button, [role="button"], a')]
        .find(b => (b.innerText || '').trim().toLowerCase() === want) || null;
    },
    // React ignore une affectation directe de .value : il faut passer par le
    // setter natif du prototype puis émettre un 'input' bouillonnant, sinon le
    // composant garde son ancien état et le bouton reste désactivé.
    setReactValue(el, value) {
      const proto = el instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    },
    // Le textarea de sauvegarde, et lui seul.
    //
    // Aucun repli sur « le premier textarea venu » : le panneau de restauration
    // est replié tant qu'on n'a pas cliqué « Restore Companion », et la page
    // porte d'autres textareas de contenu (« Write something. »). Un repli
    // large y déverserait le JSON sans que rien ne le signale.
    backupTextarea() {
      const labels = [...document.querySelectorAll('p, label, span, div')]
        .filter(n => (n.textContent || '').trim().startsWith('Paste Companion Backup'));
      for (const lab of labels) {
        const scope = lab.parentElement || document;
        const ta = scope.querySelector('textarea')
                || (scope.parentElement && scope.parentElement.querySelector('textarea'));
        if (ta) return ta;
      }
      // À défaut du libellé, le textarea monospace de la section sauvegarde.
      return document.querySelector('textarea[style*="monospace"]') || null;
    },
    // Saucepan affiche ses refus sous « Validation errors: ». C'est ainsi
    // qu'on a appris son schéma ; on continue de les lire pour les journaliser.
    validationErrors() {
      const node = [...document.querySelectorAll('div, p, span')]
        .find(n => (n.textContent || '').trim().startsWith('Validation errors'));
      return node ? node.innerText.trim() : null;
    }
  };
  return true;
}
"""


class Driver:
    """Un onglet du navigateur de l'utilisateur, avec quelques raccourcis."""

    def __init__(self, page, log=print):
        self.page = page
        self._log = log
        # Correspondance « nom de page » → index de tuile dans la barre
        # latérale de Saucepan, apprise en cliquant (voir saucepan.py).
        self.rail_cache = {}

    # -- navigation ---------------------------------------------------------

    def goto(self, url, timeout=60_000, expect_ok=True):
        """Navigue, et signale explicitement une page d'erreur.

        Sans ce contrôle, une URL fausse mène à une page 404 dont l'échec ne
        se manifeste que bien plus loin, sous une forme incompréhensible.
        """
        response = self.page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        if expect_ok and response is not None and response.status >= 400:
            raise DriverError(
                f"{response.status} sur {url} — l'adresse est probablement "
                "incorrecte ou le contenu inaccessible."
            )
        self.install_helpers()
        return response

    def goto_capturing(self, url, url_fragment, timeout=60_000, settle=8_000,
                       accept=None):
        """Navigue en interceptant la réponse JSON d'un appel de la page.

        L'API de Janitor exige un jeton `Bearer` que la page détient et que
        nous n'avons pas. Plutôt que d'extraire et rejouer ce jeton, on laisse
        la page faire sa propre requête authentifiée et on lit sa réponse au
        passage. Aucune manipulation de jeton, et le procédé survit à un
        changement de mécanisme d'authentification.

        `accept(data)` : filtre facultatif, pour écarter les réponses voisines
        qui partagent le même préfixe d'URL.
        """
        captured = {}

        def on_response(response):
            if "data" in captured:
                return
            if url_fragment in response.url and response.status == 200:
                try:
                    data = response.json()
                except Exception:                                  # noqa: BLE001
                    return
                if accept is None or accept(data):
                    captured["data"] = data

        self.page.on("response", on_response)
        try:
            self.goto(url, timeout=timeout)
            # On laisse à la page le temps de lancer et recevoir son appel.
            deadline = settle
            while "data" not in captured and deadline > 0:
                self.page.wait_for_timeout(250)
                deadline -= 250
        finally:
            self.page.remove_listener("response", on_response)

        return captured.get("data")

    def install_helpers(self):
        self.page.evaluate(JS_HELPERS)

    def url(self):
        return self.page.url

    # -- lecture ------------------------------------------------------------

    def eval_js(self, js):
        return self.page.evaluate(js)

    def wait_for(self, js_condition, timeout=30_000):
        """Attend qu'une expression JS devienne vraie."""
        self.page.wait_for_function(
            f"() => {{ try {{ return !!({js_condition}); }} catch (e) {{ return false; }} }}",
            timeout=timeout,
        )

    def is_logged_out(self):
        """La session est-elle perdue sur la page courante ?

        Ne pas se contenter de l'URL ni d'un champ mot de passe : Saucepan ne
        redirige pas vers `/login` quand la session expire, il reste sur
        `/home` et remplace le menu du compte par un bouton « Sign In ». Le
        contrôle d'origine répondait donc « connecté » à une page déconnectée,
        et l'échec ne se manifestait que bien plus loin, sous une forme
        incompréhensible.
        """
        return bool(self.eval_js("""
        () => {
          const path = location.pathname.toLowerCase();
          if (path.includes('login') || path.includes('sign-in')
              || path.includes('signin')) return true;
          if (document.querySelector('input[type="password"]')) return true;
          const wanted = ['sign in', 'log in', 'sign up', 'se connecter'];
          for (const el of document.querySelectorAll('button, a, [role="button"]')) {
            const t = (el.innerText || '').trim().toLowerCase();
            if (!wanted.includes(t)) continue;
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) return true;
          }
          return false;
        }
        """))

    def validation_errors(self):
        return self.eval_js("() => window.__naos && window.__naos.validationErrors()")

    # -- interaction --------------------------------------------------------

    def button_state(self, label):
        return self.page.evaluate(
            "(t) => { const b = window.__naos.buttonByText(t);"
            " return { present: !!b, disabled: b ? !!b.disabled : null }; }",
            label,
        )

    def click_label(self, label):
        """Clique un bouton par son libellé visible.

        Les classes de Saucepan sont générées (`sc-dTvVRJ`, `hNtzVn`…) et
        changent à chaque déploiement ; le libellé, lui, est stable.

        Le clic est confié à Playwright — souris réelle sur les coordonnées de
        l'élément — plutôt qu'à `element.click()` en JavaScript. Certains
        composants n'écoutent que les événements de pointeur émis par le
        navigateur : « Create » ignorait purement et simplement le clic
        programmatique, sans erreur ni requête réseau.
        """
        found = self.page.evaluate(
            "(t) => { const b = window.__naos.buttonByText(t);"
            " if (!b) return 'introuvable';"
            " if (b.disabled) return 'désactivé';"
            " b.setAttribute('data-naos-click', '1'); return null; }",
            label,
        )
        if found:
            raise DriverError(f"Bouton « {label} » : {found}")

        try:
            self.page.click('[data-naos-click="1"]', timeout=15_000)
        finally:
            self.page.evaluate(
                "() => document.querySelectorAll('[data-naos-click]')"
                ".forEach(e => e.removeAttribute('data-naos-click'))"
            )
        return True

    def click_first_available(self, labels, what):
        for label in labels:
            state = self.button_state(label)
            if state.get("present") and not state.get("disabled"):
                self.click_label(label)
                return label
        raise DriverError(
            f"Aucun bouton {what} parmi : {', '.join(labels)}. "
            "Ajoutez le libellé exact dans saucepan.py."
        )

    def fill_backup(self, text):
        """Écrit le backup dans la zone de collage de Saucepan.

        On passe par `fill()` de Playwright plutôt que par une affectation en
        JavaScript. React attache à chaque champ un `_valueTracker` : si l'on
        pose la valeur soi-même, le tracker se met à jour en même temps, React
        conclut « rien n'a changé » et ignore l'événement. Le DOM affiche alors
        le texte tandis que l'état du composant reste vide — et « Restore
        Data » demeure désactivé. `fill()` produit une saisie que React
        reconnaît.
        """
        marked = self.page.evaluate(
            "() => { const ta = window.__naos.backupTextarea();"
            " if (!ta) return false;"
            " ta.setAttribute('data-naos-backup', '1'); return true; }"
        )
        if not marked:
            raise DriverError("Zone « Paste Companion Backup » introuvable.")

        self.page.fill('textarea[data-naos-backup="1"]', text)
        return self.page.evaluate(
            "() => window.__naos.backupTextarea().value.length")

    def upload_file(self, file_path, accept_hint="json"):
        """Dépose un fichier dans le premier input de type fichier compatible."""
        selector = f'input[type="file"][accept*="{accept_hint}"]'
        if self.page.query_selector(selector) is None:
            selector = 'input[type="file"]'
        self.page.set_input_files(selector, file_path)


# ── Contexte d'exécution ────────────────────────────────────────────────────

class BrowserSession:
    """Ouvre une session Playwright raccrochée au navigateur de l'utilisateur.

    S'utilise comme gestionnaire de contexte :

        with BrowserSession(log) as driver:
            driver.goto("https://…")
    """

    def __init__(self, log=print, browser_path=None):
        self._log = log
        self._browser_path = browser_path
        self._pw = None
        self._browser = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        ensure_browser(self._browser_path)
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.connect_over_cdp(CDP_ENDPOINT)

        # On réutilise le contexte existant : c'est lui qui porte vos cookies
        # de session, donc le contrôle Cloudflare déjà franchi.
        contexts = self._browser.contexts
        context = contexts[0] if contexts else self._browser.new_context()
        page = context.pages[0] if context.pages else context.new_page()

        # La barre latérale de l'éditeur Saucepan est repérée par sa géométrie
        # (colonne de 60 px à gauche). Dans une fenêtre étroite, la mise en
        # page bascule et les tuiles deviennent introuvables : on fixe donc une
        # taille de travail connue.
        try:
            page.set_viewport_size({"width": 1400, "height": 950})
        except Exception:                                          # noqa: BLE001
            self._log("⚠ Taille de fenêtre non imposée — barre latérale "
                      "possiblement masquée si la fenêtre est étroite.")

        self._log("Raccordé au navigateur.")
        return Driver(page, self._log)

    def __exit__(self, *exc):
        # On ne ferme pas le navigateur : il appartient à l'utilisateur.
        try:
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()
        return False
