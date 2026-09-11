# -*- coding: utf-8 -*-
"""Dofus Manager — logique (détection, focus, cyclage, raccourcis, persistance).

Aucune interaction avec la mémoire du jeu : uniquement des API de fenêtrage Win32.
"""
import copy
import ctypes
from ctypes import wintypes
from datetime import date
import json
import logging
import math
import logging.handlers
import os
import pathlib
import queue
import re
import sys
import threading
import time
import winreg

import win32api
import win32con
import win32event
import win32gui
import win32process
import winerror

APP_NAME    = "Dofus Manager"
APP_VERSION = "4.6"
APP_AUTHOR  = "Subs12"
COPYRIGHT   = f"© 2026 {APP_AUTHOR}"

# ============================================================
# PATHS & LOGGING
# ============================================================
APP_DIR = pathlib.Path.home() / ".dofus_manager"
APP_DIR.mkdir(exist_ok=True)
CONFIG_PATH  = APP_DIR / "config.json"
LAYOUT_PATH  = APP_DIR / "layout.json"
PRESETS_PATH = APP_DIR / "presets.json"
STATS_PATH   = APP_DIR / "stats.json"
LOG_PATH     = APP_DIR / "app.log"

_handlers = [logging.handlers.RotatingFileHandler(LOG_PATH, maxBytes=512_000,
                                                  backupCount=2, encoding="utf-8")]
if sys.stdout is not None:  # None dans un exe --windowed
    _handlers.append(logging.StreamHandler())
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=_handlers)
log = logging.getLogger("DofusManager")


def read_json(path, default):
    """Lit un JSON ; si le contenu n'a pas le type de `default`, renvoie `default`."""
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(data, type(default)):
                return data
            log.warning("%s : format inattendu, ignoré.", path.name)
    except Exception as e:
        log.warning("Lecture %s impossible : %s", path.name, e)
        # Sinon la prochaine sauvegarde écraserait définitivement le fichier illisible.
        try:
            os.replace(path, path.with_suffix(path.suffix + ".corrupt"))
        except OSError:
            pass
    return default


def write_json(path, data):
    """Écriture atomique : un crash en cours d'écriture ne corrompt pas le fichier."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.error("Écriture %s impossible : %s", path.name, e)
        return
    for attempt in range(5):  # antivirus / indexeur peuvent verrouiller brièvement la cible
        try:
            os.replace(tmp, path)
            return
        except PermissionError as e:
            if attempt == 4:
                log.error("Écriture %s impossible : %s", path.name, e)
            time.sleep(0.05)
        except Exception as e:
            log.error("Écriture %s impossible : %s", path.name, e)
            return


# Événements émis par les threads d'arrière-plan (raccourcis, tray) et consommés
# par le thread Tk. Tkinter n'est pas thread-safe : jamais d'appel Tk hors thread UI.
events = queue.Queue()

# ============================================================
# WIN32
# ============================================================
user32   = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_HOTKEY    = 0x0312
WM_APP_CMD   = 0x8001
WM_APP_MOUSE = 0x8002
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
VK_F21, VK_F23 = 0x84, 0x86

# Boutons de souris : RegisterHotKey ne gère que le clavier, ils passent par un crochet
# bas niveau (voir _MouseHook). Codes pseudo-VK hors de la plage des touches (0x00-0xFF)
# pour être stockés, comparés et affichés comme n'importe quel autre raccourci.
MOUSE_VK_BASE = 0x10000
MOUSE_X1  = MOUSE_VK_BASE | 1   # bouton 4 (arrière)
MOUSE_X2  = MOUSE_VK_BASE | 2   # bouton 5 (avant)
MOUSE_MID = MOUSE_VK_BASE | 3   # clic molette
_MOUSE_NAMES = {MOUSE_X1: "Souris 4", MOUSE_X2: "Souris 5", MOUSE_MID: "Clic molette"}


def is_mouse_vk(vk):
    return bool(int(vk or 0) & MOUSE_VK_BASE)


user32.GetMessageW.argtypes        = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                      wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype         = ctypes.c_int
user32.PeekMessageW.argtypes       = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                      wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM]
user32.RegisterHotKey.argtypes     = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype      = wintypes.BOOL
user32.UnregisterHotKey.argtypes   = [wintypes.HWND, ctypes.c_int]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.IsHungAppWindow.argtypes    = [wintypes.HWND]
user32.IsHungAppWindow.restype     = wintypes.BOOL
user32.ShowWindow.argtypes         = [wintypes.HWND, ctypes.c_int]
user32.ShowWindowAsync.argtypes    = [wintypes.HWND, ctypes.c_int]
user32.MapVirtualKeyW.argtypes     = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype      = wintypes.UINT
user32.GetKeyNameTextW.argtypes    = [wintypes.LPARAM, wintypes.LPWSTR, ctypes.c_int]
user32.VkKeyScanW.argtypes         = [wintypes.WCHAR]
user32.VkKeyScanW.restype          = wintypes.SHORT
user32.GetAsyncKeyState.argtypes   = [ctypes.c_int]
user32.GetAsyncKeyState.restype    = wintypes.SHORT
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                 wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.QueryFullProcessImageNameW.restype  = wintypes.BOOL


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", ctypes.c_ulong)]


user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype  = wintypes.HANDLE
user32.GetMonitorInfoW.argtypes   = [wintypes.HANDLE, ctypes.POINTER(_MONITORINFO)]


def enable_dpi_awareness():
    """Rendu net sur écrans HiDPI et coordonnées cohérentes entre moniteurs."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def get_monitor_rect(hwnd):
    try:
        hmon = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(_MONITORINFO)
        if hmon and user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r = mi.rcMonitor
            return (r.left, r.top, r.right, r.bottom)
    except Exception:
        pass
    return None


# ============================================================
# TOUCHES
# ============================================================
_EXTENDED_VK = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C}


def vk_name(vk):
    vk = int(vk)
    if is_mouse_vk(vk):
        return _MOUSE_NAMES.get(vk, f"Souris {vk & 0xFF}")
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x6F}"
    try:
        sc = user32.MapVirtualKeyW(vk, 0)
        if sc:
            if vk in _EXTENDED_VK:
                sc |= 0xE000
            buf = ctypes.create_unicode_buffer(64)
            if user32.GetKeyNameTextW(sc << 16, buf, 64) > 0 and buf.value.strip():
                return buf.value
    except Exception:
        pass
    return f"VK {vk}"


def mods_name(mods):
    parts = []
    if mods & MOD_CONTROL: parts.append("Ctrl")
    if mods & MOD_ALT:     parts.append("Alt")
    if mods & MOD_SHIFT:   parts.append("Shift")
    if mods & MOD_WIN:     parts.append("Win")
    return "+".join(parts)


def current_mods():
    """Modificateurs pressés à l'instant t : RegisterHotKey les fournit, le crochet souris non."""
    m = 0
    if user32.GetAsyncKeyState(0x11) & 0x8000: m |= MOD_CONTROL
    if user32.GetAsyncKeyState(0x12) & 0x8000: m |= MOD_ALT
    if user32.GetAsyncKeyState(0x10) & 0x8000: m |= MOD_SHIFT
    if (user32.GetAsyncKeyState(0x5B) | user32.GetAsyncKeyState(0x5C)) & 0x8000: m |= MOD_WIN
    return m


def combo_name(vk, mods=0):
    if not vk:
        return "—"
    m = mods_name(mods)
    return f"{m}+{vk_name(vk)}" if m else vk_name(vk)


_KEYSYM_TO_VK = {
    "Return": 0x0D, "Tab": 0x09, "space": 0x20, "BackSpace": 0x08, "Delete": 0x2E,
    "Insert": 0x2D, "Home": 0x24, "End": 0x23, "Prior": 0x21, "Next": 0x22,
    "Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28, "Pause": 0x13,
    "KP_0": 0x60, "KP_1": 0x61, "KP_2": 0x62, "KP_3": 0x63, "KP_4": 0x64,
    "KP_5": 0x65, "KP_6": 0x66, "KP_7": 0x67, "KP_8": 0x68, "KP_9": 0x69,
    "KP_Multiply": 0x6A, "KP_Add": 0x6B, "KP_Subtract": 0x6D, "KP_Divide": 0x6F,
}
_MODIFIER_KEYSYMS = {"Control_L", "Control_R", "Alt_L", "Alt_R", "Shift_L", "Shift_R",
                     "Win_L", "Win_R", "Super_L", "Super_R"}


def event_to_combo(event):
    """(vk, mods) depuis un événement clavier Tk, ou None pour une touche modificatrice seule."""
    ks = getattr(event, "keysym", "")
    if ks in _MODIFIER_KEYSYMS:
        return None
    vk = None
    if ks.startswith("F") and ks[1:].isdigit() and 1 <= int(ks[1:]) <= 24:
        vk = 0x6F + int(ks[1:])
    elif ks in _KEYSYM_TO_VK:
        vk = _KEYSYM_TO_VK[ks]
    elif getattr(event, "keycode", 0):
        vk = int(event.keycode) & 0xFF  # Tk/Windows : keycode == virtual-key
    if not vk:
        return None
    mods = 0
    if event.state & 0x0004:  mods |= MOD_CONTROL
    if event.state & 0x20000: mods |= MOD_ALT
    if event.state & 0x0001:  mods |= MOD_SHIFT
    return vk, mods


# ============================================================
# TITRES DE FENÊTRES
# ============================================================
_VERSION_RE  = re.compile(r"^\d+(\.\d+)+$")
_NOISE_WORDS = {"dofus", "release", "beta", "bêta", "alpha"}


def split_title(title):
    """'Exoticlozie - Sadida - 3.6.11.15 - Release' -> ('Exoticlozie', 'Sadida')."""
    parts = [p.strip() for p in title.split(" - ") if p.strip()]
    parts = [p for p in parts if not _VERSION_RE.match(p) and p.lower() not in _NOISE_WORDS]
    if not parts:
        return title.strip(), ""
    return parts[0], " - ".join(parts[1:])


def char_name(title):
    return split_title(title)[0]


# ============================================================
# CONFIG
# ============================================================
def _to_int(val, default=0):
    try:
        return int(val or 0)
    except (TypeError, ValueError):
        return default


class Config:
    DEFAULTS = {
        "theme": "dark",
        "vkey_next": VK_F23, "mods_next": 0,
        "vkey_prev": VK_F21, "mods_prev": 0,
        "direct_keys": [],            # [{"vkey": int, "mods": int}, ...] -> perso 1..N
        "auto_maximize": True,
        "show_notifs": True,
        "show_overlay": True,
        "overlay_ms": 900,
        "always_on_top": False,
        "minimize_to_tray": True,
        "start_minimized": False,
        "auto_apply_last": True,      # reprend le cyclage automatiquement au démarrage
        "active_preset": "",
        "preset_keys": {},            # {nom_preset: {"vkey", "mods"}}
        "char_classes": {},           # {perso: classe} mémorisé pour les persos déconnectés
        "dismissed_update_tag": "",   # version refusée : pas de re-proposition auto tant qu'elle est la dernière
        "turn_focus": False,          # affiche le perso qui clignote dans la barre des tâches (début de tour)
        "turn_focus_cycle_only": True,
        "mouse_passthrough": False,   # un bouton de souris lié est consommé (pas transmis au jeu)
    }

    def __init__(self):
        data = read_json(CONFIG_PATH, {})
        for k, v in self.DEFAULTS.items():
            val = data.get(k, v)
            if isinstance(v, bool):
                val = bool(val)
            elif isinstance(v, int):
                val = _to_int(val, v)
            elif not isinstance(val, type(v)):
                val = v  # ex. "theme": null dans un config.json édité à la main
            setattr(self, k, copy.deepcopy(val))  # jamais d'alias vers DEFAULTS
        if self.theme not in ("dark", "light", "system"):
            self.theme = "dark"
        # target : "pos:N" (position N du cycle) ou "char:Nom" (personnage précis)
        self.direct_keys = [{"vkey": _to_int(d.get("vkey")), "mods": _to_int(d.get("mods")),
                             "target": str(d.get("target") or f"pos:{i + 1}")}
                            for i, d in enumerate(x for x in self.direct_keys if isinstance(x, dict))]
        self.preset_keys = {str(k): {"vkey": _to_int(v.get("vkey")), "mods": _to_int(v.get("mods"))}
                            for k, v in self.preset_keys.items() if isinstance(v, dict) and _to_int(v.get("vkey"))}

    def save(self):
        write_json(CONFIG_PATH, {k: getattr(self, k) for k in self.DEFAULTS})

    def hotkey_spec(self):
        return {"next": (self.vkey_next, self.mods_next),
                "prev": (self.vkey_prev, self.mods_prev),
                "directs": [(d["vkey"], d["mods"], d["target"]) for d in self.direct_keys],
                "presets": [(v["vkey"], v["mods"], n) for n, v in self.preset_keys.items()]}


config = Config()

# ============================================================
# LAYOUT & PRESETS
# ============================================================
DEFAULT_PRESETS = {"Équipe principale": ["Exoticlozie", "Schokocafe", "Schokobun", "Schokoarc"]}


def load_layout():
    return {str(k): _to_int(v) for k, v in read_json(LAYOUT_PATH, {}).items()}


def save_layout(mapping):
    write_json(LAYOUT_PATH, mapping)


def load_presets():
    if not PRESETS_PATH.exists():
        write_json(PRESETS_PATH, DEFAULT_PRESETS)
        return dict(DEFAULT_PRESETS)
    data = read_json(PRESETS_PATH, {})
    return {str(k): [str(n) for n in v if isinstance(n, str) and n.strip()]
            for k, v in data.items() if isinstance(v, list)}


def save_presets(mapping):
    write_json(PRESETS_PATH, mapping)


# ============================================================
# DÉMARRAGE AVEC WINDOWS
# ============================================================
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_NAME = "DofusManager"


def _startup_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    main = os.path.abspath(sys.argv[0])
    pyw = pathlib.Path(sys.executable).with_name("pythonw.exe")
    exe = pyw if pyw.exists() else sys.executable
    return f'"{exe}" "{main}"'


def is_startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as k:
            winreg.QueryValueEx(k, _RUN_NAME)
            return True
    except OSError:
        return False


def set_startup_enabled(enabled):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, _RUN_NAME, 0, winreg.REG_SZ, _startup_command())
            else:
                try:
                    winreg.DeleteValue(k, _RUN_NAME)
                except FileNotFoundError:
                    pass
    except Exception as e:
        log.error("Démarrage Windows : %s", e)


# ============================================================
# STATS DE SESSION (accès concurrent : thread raccourcis + thread UI)
# ============================================================
class SessionStats:
    """Stats de la session + historique journalier persistant (stats.json)."""

    def __init__(self):
        self._lock = threading.Lock()
        raw = read_json(STATS_PATH, {"days": {}}).get("days")
        days = {}
        for key, d in (raw.items() if isinstance(raw, dict) else []):
            if not isinstance(d, dict):
                continue
            chars = {str(n): {"seconds": float(v.get("seconds") or 0), "count": _to_int(v.get("count"))}
                     for n, v in (d.get("chars") or {}).items() if isinstance(v, dict)} \
                if isinstance(d.get("chars"), dict) else {}
            days[str(key)] = {"chars": chars, "switches": _to_int(d.get("switches"))}
        self.history = {"days": days}
        self._new_session()

    def _new_session(self):
        self._times, self._counts = {}, {}
        self._cur, self._cur_start = None, None
        self._session_start = time.time()
        self.switches = 0
        self._flushed, self._flushed_switches = {}, 0  # déjà reporté dans l'historique

    def reset(self):
        """Remet la session à zéro (ce qui a été joué reste dans l'historique)."""
        self.flush()
        with self._lock:
            self._new_session()

    def on_focus(self, name):
        with self._lock:
            if name == self._cur:
                return  # re-focus du perso déjà affiché : pas un changement
            now = time.time()
            if self._cur:
                self._times[self._cur] = self._times.get(self._cur, 0) + now - self._cur_start
            self._cur, self._cur_start = name, now
            self._counts[name] = self._counts.get(name, 0) + 1
            self.switches += 1

    def snapshot(self):
        with self._lock:
            out = {n: {"seconds": s, "count": self._counts.get(n, 0)} for n, s in self._times.items()}
            if self._cur:
                d = out.setdefault(self._cur, {"seconds": 0, "count": self._counts.get(self._cur, 0)})
                d["seconds"] += time.time() - self._cur_start
            return out

    def duration(self):
        return time.time() - self._session_start

    def _unflushed(self, snap):
        out = {}
        for n, v in snap.items():
            fs, fc = self._flushed.get(n, (0.0, 0))
            out[n] = (max(v["seconds"] - fs, 0.0), max(v["count"] - fc, 0))
        return out

    def flush(self):
        """Reporte dans l'historique du jour ce qui n'y est pas encore, puis sauvegarde."""
        snap = self.snapshot()
        with self._lock:
            day = self.history["days"].setdefault(date.today().isoformat(), {"chars": {}, "switches": 0})
            for n, (ds, dc) in self._unflushed(snap).items():
                if ds or dc:
                    e = day["chars"].setdefault(n, {"seconds": 0.0, "count": 0})
                    e["seconds"] += ds
                    e["count"] += dc
                self._flushed[n] = (snap[n]["seconds"], snap[n]["count"])
            day["switches"] += self.switches - self._flushed_switches
            self._flushed_switches = self.switches
            data = json.loads(json.dumps(self.history))
        write_json(STATS_PATH, data)

    def totals(self, days=None):
        """Cumul historique + session non encore sauvegardée. days=None : depuis le début."""
        snap = self.snapshot()
        today = date.today()
        chars, switches = {}, 0
        with self._lock:
            for key, d in self.history["days"].items():
                try:
                    age = (today - date.fromisoformat(key)).days
                except ValueError:
                    continue
                if days is not None and age >= days:
                    continue
                for n, v in d.get("chars", {}).items():
                    e = chars.setdefault(n, {"seconds": 0.0, "count": 0})
                    e["seconds"] += v.get("seconds", 0)
                    e["count"] += v.get("count", 0)
                switches += d.get("switches", 0)
            for n, (ds, dc) in self._unflushed(snap).items():
                e = chars.setdefault(n, {"seconds": 0.0, "count": 0})
                e["seconds"] += ds
                e["count"] += dc
            switches += self.switches - self._flushed_switches
        return chars, switches

    def clear_history(self):
        snap = self.snapshot()
        with self._lock:
            self.history = {"days": {}}
            self._flushed = {n: (v["seconds"], v["count"]) for n, v in snap.items()}
            self._flushed_switches = self.switches
        write_json(STATS_PATH, self.history)


stats = SessionStats()

# ============================================================
# DÉTECTION DES FENÊTRES
# ============================================================
SELF_PID = os.getpid()
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000  # aucun droit sur la mémoire du processus


def get_process_name(pid):
    h = None
    try:
        h = win32api.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        buf = ctypes.create_unicode_buffer(1024)  # chemins longs (> MAX_PATH)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(int(h), 0, buf, ctypes.byref(size)):
            return pathlib.Path(buf.value).name.lower()
    except Exception:
        pass
    finally:
        if h:
            try:
                win32api.CloseHandle(h)
            except Exception:
                pass
    return ""


def is_dofus_process(pid):
    # Détection par nom d'exécutable uniquement : les titres de fenêtres du jeu ne
    # contiennent pas "dofus", un repli sur le titre n'attrapait que des faux positifs
    # (onglets de navigateur, explorateur…).
    if not pid or pid == SELF_PID:
        return False
    name = get_process_name(pid)
    return name.startswith("dofus") and "manager" not in name


def _is_candidate(hwnd):
    if not win32gui.IsWindowVisible(hwnd):
        return False
    if win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) & win32con.WS_EX_TOOLWINDOW:
        return False
    if win32gui.GetWindow(hwnd, win32con.GW_OWNER):
        return False
    return bool(win32gui.GetWindowText(hwnd).strip())


def enum_dofus_windows():
    out, pid_cache = [], {}

    def cb(hwnd, _):
        try:
            if not _is_candidate(hwnd):
                return
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid not in pid_cache:
                pid_cache[pid] = is_dofus_process(pid)
            if pid_cache[pid]:
                title = win32gui.GetWindowText(hwnd).strip()
                name, klass = split_title(title)
                out.append({"hwnd": hwnd, "pid": pid, "title": title,
                            "name": name, "klass": klass})
        except Exception:
            pass

    win32gui.EnumWindows(cb, None)
    return out


def focus_window(hwnd, maximize=True):
    if not win32gui.IsWindow(hwnd):
        log.warning("Focus ignoré : fenêtre fermée (hwnd=%s)", hwnd)
        return False
    try:
        # Fenêtre figée (chargement, freeze du client) : ShowWindow synchrone bloquerait
        # le thread des raccourcis, et donc tous les autres raccourcis.
        show = user32.ShowWindowAsync if user32.IsHungAppWindow(hwnd) else user32.ShowWindow
        if maximize:
            # Un seul SW_MAXIMIZE : un SW_RESTORE préalable provoque un flash de la
            # fenêtre à sa taille « restaurée » (visible en multi-écran).
            if not (win32gui.GetWindowPlacement(hwnd)[1] == win32con.SW_SHOWMAXIMIZED):
                show(hwnd, win32con.SW_MAXIMIZE)
        elif win32gui.IsIconic(hwnd):
            # Ne pas SW_RESTORE une fenêtre maximisée : ça la réduirait.
            show(hwnd, win32con.SW_RESTORE)

        fg = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        cur_tid = kernel32.GetCurrentThreadId()
        attached = bool(fg_tid and fg_tid != cur_tid and
                        user32.AttachThreadInput(cur_tid, fg_tid, True))
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(cur_tid, fg_tid, False)

        stats.on_focus(char_name(win32gui.GetWindowText(hwnd)))
        return True
    except Exception as e:
        log.error("Focus error: %s", e)
        return False


# ============================================================
# CYCLAGE
# ============================================================
class WindowCycler:
    def __init__(self):
        self._lock = threading.Lock()
        self.order = []   # [(pos, hwnd, title)] trié
        self._idx = -1
        self._last = 0.0

    def set_order(self, items):
        with self._lock:
            self.order = sorted([x for x in items if x[0] > 0], key=lambda t: t[0])
            self._idx = -1
        log.info("Cycle order: %d windows", len(self.order))

    def snapshot(self):
        with self._lock:
            return list(self.order)

    def _prune(self):
        alive = [x for x in self.order if win32gui.IsWindow(x[1])]
        if len(alive) != len(self.order):
            self.order, self._idx = alive, -1

    def _sync(self):
        fg = user32.GetForegroundWindow()
        for i, (_, h, _) in enumerate(self.order):
            if h == fg:
                self._idx = i
                return

    def step(self, delta=0, goto=None):
        with self._lock:
            now = time.time()
            if now - self._last < 0.12:  # anti-rebond
                return None
            self._last = now
            self._prune()
            if not self.order:
                return None
            if goto is not None:
                if not 0 <= goto < len(self.order):
                    return None
                self._idx = goto
            else:
                self._sync()
                self._idx = (self._idx + delta) % len(self.order)
            return self.order[self._idx]


cycler = WindowCycler()


def do_cycle(delta=0, goto=None):
    target = cycler.step(delta, goto)
    if target and focus_window(target[1], config.auto_maximize):
        title = win32gui.GetWindowText(target[1]).strip() or target[2]  # titre à jour pour l'overlay
        events.put(("switch", target[0], target[1], title))


_last_named = [0.0]


def focus_by_name(name):
    """Affiche un personnage précis (même hors du cycle)."""
    now = time.time()
    if now - _last_named[0] < 0.12:
        return
    _last_named[0] = now
    w = next((w for w in enum_dofus_windows() if w["name"].lower() == name.lower()), None)
    if not w:
        events.put(("notice", f"{name} n'est pas connecté."))
        return
    if focus_window(w["hwnd"], config.auto_maximize):
        order = next((o for o, h, _ in cycler.snapshot() if h == w["hwnd"]), 0)
        events.put(("switch", order, w["hwnd"], w["title"]))


def target_label(target):
    kind, _, val = str(target).partition(":")
    return val if kind == "char" else f"Position {val}"


def run_action(action):
    if not action:
        return
    kind, arg = action
    if kind == "step":
        do_cycle(arg)
    elif kind == "target":
        t, _, val = str(arg).partition(":")
        if t == "char":
            focus_by_name(val)
        elif val.isdigit():
            do_cycle(goto=int(val) - 1)
    elif kind == "preset":
        events.put(("preset_hotkey", arg))  # appliqué par le thread UI (état de l'interface)


# ============================================================
# DISPOSITION DES FENÊTRES (mosaïque / multi-écrans)
# ============================================================
_SWP_NOZORDER, _SWP_NOACTIVATE = 0x0004, 0x0010


def list_monitors():
    mons = []
    try:
        for hmon, _hdc, _rect in win32api.EnumDisplayMonitors(None, None):
            info = win32api.GetMonitorInfo(hmon)
            mons.append({"rect": tuple(info["Monitor"]), "work": tuple(info["Work"]),
                         "primary": bool(info.get("Flags", 0) & 1)})
    except Exception as e:
        log.error("Écrans : %s", e)
    mons.sort(key=lambda m: (not m["primary"], m["rect"][0], m["rect"][1]))
    return mons


def _frame_margins(hwnd):
    """Bordures invisibles de Windows 10/11 (≈7 px) à compenser pour des tuiles jointives."""
    r = wintypes.RECT()
    try:
        if ctypes.windll.dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), 9, ctypes.byref(r),
                                                      ctypes.sizeof(r)) == 0:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            return r.left - left, r.top - top, right - r.right, bottom - r.bottom
    except Exception:
        pass
    return 0, 0, 0, 0


def _place(hwnd, x, y, w, h):
    if win32gui.IsIconic(hwnd) or win32gui.GetWindowPlacement(hwnd)[1] == win32con.SW_SHOWMAXIMIZED:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    ml, mt, mr, mb = _frame_margins(hwnd)
    win32gui.SetWindowPos(hwnd, 0, x - ml, y - mt, w + ml + mr, h + mt + mb,
                          _SWP_NOZORDER | _SWP_NOACTIVATE)


def arrange_windows(hwnds, mode, monitor_index=0):
    """mode : 'single' (tous en plein écran sur un écran), 'grid' (mosaïque sur un écran),
    'spread' (un perso par écran), 'maximize' (plein écran là où ils sont)."""
    # Une fenêtre figée bloquerait SetWindowPos (donc l'interface) : on la saute.
    hwnds = [h for h in hwnds if win32gui.IsWindow(h) and not user32.IsHungAppWindow(h)]
    mons = list_monitors()
    if not hwnds or not mons:
        return 0
    try:
        if mode == "grid":
            left, top, right, bottom = mons[min(monitor_index, len(mons) - 1)]["work"]
            cols = math.ceil(math.sqrt(len(hwnds)))
            rows = math.ceil(len(hwnds) / cols)
            cw, ch = (right - left) // cols, (bottom - top) // rows
            for i, h in enumerate(hwnds):
                r, c = divmod(i, cols)
                _place(h, left + c * cw, top + r * ch, cw, ch)
        elif mode == "single":
            left, top, right, bottom = mons[min(monitor_index, len(mons) - 1)]["work"]
            for h in hwnds:
                _place(h, left, top, right - left, bottom - top)  # déplace sur l'écran choisi
                win32gui.ShowWindow(h, win32con.SW_MAXIMIZE)
        elif mode == "spread":
            for i, h in enumerate(hwnds):
                left, top, right, bottom = mons[i % len(mons)]["work"]
                _place(h, left, top, right - left, bottom - top)
                win32gui.ShowWindow(h, win32con.SW_MAXIMIZE)
        elif mode == "maximize":
            for h in hwnds:
                win32gui.ShowWindow(h, win32con.SW_MAXIMIZE)
    except Exception as e:
        log.error("Disposition : %s", e)
    log.info("Disposition %s : %d fenêtres", mode, len(hwnds))
    return len(hwnds)


# ============================================================
# RACCOURCIS GLOBAUX
# ============================================================
_HK_NEXT, _HK_PREV, _HK_DIRECT, _HK_PRESET = 1, 2, 10, 100


# ============================================================
# CROCHET SOURIS (boutons 4 / 5 / molette)
# ============================================================
WH_MOUSE_LL = 14
WM_MBUTTONDOWN, WM_MBUTTONUP = 0x0207, 0x0208
WM_XBUTTONDOWN, WM_XBUTTONUP = 0x020B, 0x020C
_MOUSE_DOWN = {WM_MBUTTONDOWN, WM_XBUTTONDOWN}
_MOUSE_UP   = {WM_MBUTTONUP, WM_XBUTTONUP}


class _MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


_LL_PROC = ctypes.WINFUNCTYPE(wintypes.LPARAM, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.argtypes   = [ctypes.c_int, _LL_PROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype    = wintypes.HHOOK
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.CallNextHookEx.argtypes      = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype       = wintypes.LPARAM


def _mouse_vk_of(msg, mouse_data):
    if msg in (WM_XBUTTONDOWN, WM_XBUTTONUP):
        btn = (int(mouse_data) >> 16) & 0xFFFF   # XBUTTON1 = 1 (bouton 4), XBUTTON2 = 2 (bouton 5)
        return MOUSE_VK_BASE | btn if btn in (1, 2) else 0
    if msg in (WM_MBUTTONDOWN, WM_MBUTTONUP):
        return MOUSE_MID
    return 0


class _MouseHook:
    """Crochet bas niveau WH_MOUSE_LL : seule façon de capter les boutons 4/5 d'une souris,
    RegisterHotKey ignorant tout ce qui n'est pas le clavier. À installer depuis un thread
    qui pompe les messages (thread des raccourcis ou thread Tk) — Windows y appelle le
    rappel. Le rappel doit rendre la main vite (Windows le désactive au bout de ~300 ms) :
    on se contente donc d'y poster un message, jamais d'y déplacer une fenêtre."""

    def __init__(self, on_button):
        self._on_button = on_button          # (vk, is_down) -> True si l'événement est consommé
        self._hook = None
        self._proc = _LL_PROC(self._cb)      # référence gardée : sinon ramassée par le GC
        self._swallowed = set()

    @property
    def active(self):
        return bool(self._hook)

    def install(self):
        if self._hook:
            return True
        self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, None, 0)
        if not self._hook:
            log.warning("Crochet souris non installé : boutons de souris indisponibles.")
        return bool(self._hook)

    def remove(self):
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None
        self._swallowed.clear()

    def _cb(self, code, wparam, lparam):
        if code == 0:
            try:
                msg = int(wparam)
                if msg in _MOUSE_DOWN or msg in _MOUSE_UP:
                    info = ctypes.cast(lparam, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
                    vk = _mouse_vk_of(msg, info.mouseData)
                    if vk:
                        down = msg in _MOUSE_DOWN
                        if down:
                            if self._on_button(vk, True):
                                self._swallowed.add(vk)
                                return 1
                        elif vk in self._swallowed:
                            # Jamais un relâchement orphelin : le jeu resterait « bouton enfoncé ».
                            self._swallowed.discard(vk)
                            self._on_button(vk, False)
                            return 1
            except Exception as e:
                log.error("Crochet souris : %s", e)
        return user32.CallNextHookEx(self._hook, code, wparam, lparam)


class MouseCapture:
    """Capte le prochain bouton 4/5/molette, pour l'assignation d'un raccourci.
    Installé depuis le thread Tk, qui pompe déjà les messages."""

    def __init__(self):
        self.result = None
        self._hook = _MouseHook(self._press)

    def start(self):
        self.result = None
        return self._hook.install()

    def stop(self):
        self._hook.remove()

    def _press(self, vk, is_down):
        if is_down and self.result is None:
            self.result = (vk, current_mods())
        return True   # toujours consommé : le clic ne doit pas atteindre la fenêtre derrière


class HotkeyManager:
    """Thread dédié bloqué sur GetMessageW (0 % CPU au repos), réveillé par
    PostThreadMessageW pour appliquer une nouvelle config, se mettre en pause ou s'arrêter."""

    def __init__(self):
        self._q = queue.Queue()
        self._tid = None
        self._ready = threading.Event()
        self._t = None
        self._actions = {}   # id de raccourci -> action (utilisé uniquement dans le thread)
        self._mouse_binds = {}   # (vk souris, mods) -> id de raccourci
        self._mouse = _MouseHook(self._on_mouse)
        self.paused = False

    def start(self, spec):
        if self._t and self._t.is_alive():
            return
        self._t = threading.Thread(target=self._run, args=(spec,), daemon=True)
        self._t.start()
        self._ready.wait(2)

    def _send(self, cmd, data=None):
        self._q.put((cmd, data))
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_APP_CMD, 0, 0)

    def apply(self, spec):
        self._send("apply", spec)

    def set_paused(self, paused):
        self.paused = paused
        self._send("pause", paused)

    def stop(self):
        self._send("stop")

    def _register(self, spec):
        ids, failed = [], []
        self._actions = {_HK_NEXT: ("step", +1), _HK_PREV: ("step", -1)}
        entries = [(_HK_NEXT, spec["next"], "Suivant"), (_HK_PREV, spec["prev"], "Précédent")]
        for i, (vk, mods, target) in enumerate(spec["directs"][:_HK_PRESET - _HK_DIRECT]):
            self._actions[_HK_DIRECT + i] = ("target", target)
            entries.append((_HK_DIRECT + i, (vk, mods), target_label(target)))
        for j, (vk, mods, name) in enumerate(spec.get("presets", [])):
            self._actions[_HK_PRESET + j] = ("preset", name)
            entries.append((_HK_PRESET + j, (vk, mods), f"Preset {name}"))
        self._mouse_binds = {}
        mouse_labels = []
        for hk_id, (vk, mods), label in entries:
            if not vk:
                continue
            if is_mouse_vk(vk):
                self._mouse_binds[(int(vk), int(mods))] = hk_id
                mouse_labels.append(f"{label} ({combo_name(vk, mods)})")
            elif user32.RegisterHotKey(None, hk_id, MOD_NOREPEAT | int(mods), int(vk)):
                ids.append(hk_id)
            else:
                failed.append(f"{label} ({combo_name(vk, mods)})")
        if self._mouse_binds and not self._mouse.install():
            self._mouse_binds = {}
            failed.extend(mouse_labels)
        elif not self._mouse_binds:
            self._mouse.remove()
        if failed:
            log.warning("Raccourcis non enregistrés (déjà pris par une autre appli ?) : %s", failed)
        events.put(("hotkeys", failed))
        return ids

    def _unregister(self, ids):
        for hk_id in ids:
            user32.UnregisterHotKey(None, hk_id)
        self._mouse_binds = {}
        self._mouse.remove()

    def _on_mouse(self, vk, is_down):
        """Appelé dans le crochet : ne fait que router, le travail se fait dans la boucle."""
        if not any(v == vk for v, _ in self._mouse_binds):
            return False
        if is_down:
            hk_id = self._mouse_binds.get((vk, current_mods()))
            if hk_id is None:
                return False   # combinaison non liée (ex. Ctrl+Souris 5) : laissée au jeu
            if self._tid:
                user32.PostThreadMessageW(self._tid, WM_APP_MOUSE, hk_id, 0)
        return not config.mouse_passthrough

    def _run(self, spec):
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # crée la file de messages
        self._tid = kernel32.GetCurrentThreadId()
        self._ready.set()
        ids = [] if self.paused else self._register(spec)
        if not self._q.empty():
            # Commande envoyée avant que _tid soit connu : le message de réveil n'est jamais parti.
            user32.PostThreadMessageW(self._tid, WM_APP_CMD, 0, 0)
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_APP_CMD:
                stop = False
                while True:
                    try:
                        cmd, data = self._q.get_nowait()
                    except queue.Empty:
                        break
                    if cmd == "stop":
                        stop = True
                    elif cmd == "apply":
                        spec = data
                        self._unregister(ids)
                        ids = [] if self.paused else self._register(spec)
                    elif cmd == "pause":
                        self._unregister(ids)
                        ids = [] if data else self._register(spec)
                if stop:
                    break
            elif msg.message in (WM_HOTKEY, WM_APP_MOUSE):
                try:
                    run_action(self._actions.get(msg.wParam))
                except Exception as e:
                    log.error("Hotkey dispatch error: %s", e)
        self._unregister(ids)


hotkeys = HotkeyManager()

# ============================================================
# TOUR DE JEU (clignotement de la barre des tâches)
# ============================================================
_HSHELL_FLASH = 0x8006
user32.RegisterShellHookWindow.argtypes   = [wintypes.HWND]
user32.DeregisterShellHookWindow.argtypes = [wintypes.HWND]


def _is_game_window(hwnd):
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return is_dofus_process(pid)
    except Exception:
        return False


class TurnWatcher:
    """Affiche le perso dont la fenêtre clignote dans la barre des tâches (début de tour).

    Repose uniquement sur la notification shell HSHELL_FLASH que Windows envoie à une
    fenêtre cachée du manager : aucun accès au processus du jeu.
    """
    _CLASS = "DofusManagerTurnWatcher"

    def __init__(self):
        self._hwnd = None
        self._shell_msg = 0
        self._last = {}

    def start(self):
        if self._hwnd is None:
            threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        if self._hwnd:
            try:
                win32gui.PostMessage(self._hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:
                pass

    def _run(self):
        try:
            wc = win32gui.WNDCLASS()
            wc.lpszClassName = self._CLASS
            wc.hInstance = win32api.GetModuleHandle(None)
            wc.lpfnWndProc = self._wndproc
            try:
                win32gui.RegisterClass(wc)
            except win32gui.error:
                pass
            # Fenêtre top-level jamais affichée : une fenêtre message-only ne reçoit pas les notifications shell.
            self._hwnd = win32gui.CreateWindowEx(0, self._CLASS, self._CLASS, 0, 0, 0, 0, 0,
                                                 0, 0, wc.hInstance, None)
            self._shell_msg = win32gui.RegisterWindowMessage("SHELLHOOK")
            if not user32.RegisterShellHookWindow(self._hwnd):
                log.warning("Suivi des tours indisponible.")
                return
            win32gui.PumpMessages()
        except Exception as e:
            log.error("Suivi des tours : %s", e)
        finally:
            self._hwnd = None

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if self._shell_msg and msg == self._shell_msg:
            if wparam == _HSHELL_FLASH and config.turn_focus:
                try:
                    self._on_flash(lparam)
                except Exception as e:
                    log.error("Suivi des tours : %s", e)
            return 0
        if msg == win32con.WM_CLOSE:
            user32.DeregisterShellHookWindow(hwnd)
            win32gui.DestroyWindow(hwnd)
            return 0
        if msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _on_flash(self, hwnd):
        if hotkeys.paused or not win32gui.IsWindow(hwnd):
            return
        fg = user32.GetForegroundWindow()
        # Déjà affiché, ou l'utilisateur est hors du jeu (chat, navigateur) : on ne vole pas le focus.
        if hwnd == fg or not _is_game_window(fg):
            return
        order = next((o for o, h, _ in cycler.snapshot() if h == hwnd), 0)
        if not order and (config.turn_focus_cycle_only or not _is_game_window(hwnd)):
            return
        now = time.time()
        if now - self._last.get(hwnd, 0) < 1.5:  # une fenêtre clignote plusieurs fois par tour
            return
        self._last[hwnd] = now
        if focus_window(hwnd, config.auto_maximize):
            title = win32gui.GetWindowText(hwnd).strip()
            events.put(("switch", order, hwnd, title))
            log.info("Début de tour : %s", char_name(title))


turns = TurnWatcher()

# ============================================================
# INSTANCE UNIQUE
# ============================================================
_mutex = None


def acquire_single_instance():
    global _mutex
    try:
        _mutex = win32event.CreateMutex(None, False, "Global\\DofusManager_SingleInstance_Mutex")
    except Exception as e:
        # Accès refusé : le mutex existe déjà (créé par une instance d'un autre niveau de privilège).
        log.warning("Mutex d'instance : %s", e)
        return False
    return win32api.GetLastError() != winerror.ERROR_ALREADY_EXISTS
