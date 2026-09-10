# -*- coding: utf-8 -*-
# Dofus 3 Window Manager — v3.0 by Subs12
# UI minimaliste, drag & drop réel, cyclage relatif

import ctypes
from ctypes import wintypes
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import json
import os
import re
import queue
import logging
import pathlib

try:
    from PIL import Image, ImageTk
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False

try:
    import pystray
    from pystray import MenuItem as TrayItem
    _HAS_TRAY = True
except Exception:
    _HAS_TRAY = False

import sys
import winreg
import win32gui
import win32con
import win32process
import win32api
import win32event
import winerror

# ============================================================
# PATHS & LOGGING
# ============================================================
APP_DIR = pathlib.Path.home() / ".dofus_manager"
APP_DIR.mkdir(exist_ok=True)
CONFIG_PATH = APP_DIR / "config.json"
LAYOUT_PATH = APP_DIR / "layout.json"
LOG_PATH    = APP_DIR / "app.log"
ICON_PATH   = pathlib.Path.home() / "Downloads" / "Dofus__meraude.png"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"),
              logging.StreamHandler()]
)
log = logging.getLogger("DofusManager")

# ============================================================
# WIN32 CONSTANTS
# ============================================================
WM_HOTKEY    = 0x0312
MOD_NOREPEAT = 0x4000
MOD_ALT      = 0x0001
MOD_CONTROL  = 0x0002
MOD_SHIFT    = 0x0004
MOD_WIN      = 0x0008

VK_F21 = 0x84
VK_F23 = 0x86

user32   = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
PM_REMOVE = 0x0001

HK_NEXT  = 1
HK_PREV  = 2
HK_DIRECT_BASE = 10

# ============================================================
# THEME — minimaliste, inspiré Linear / Arc
# ============================================================
THEMES = {
    "dark": {
        "BG":         "#0F0F11",   # fond global, presque noir
        "SURFACE":    "#17171A",   # cartes, panels
        "SURFACE_2":  "#1E1E22",   # éléments interactifs (hover)
        "BORDER":     "#26262B",   # séparateurs très subtils
        "TEXT":       "#E8E8EA",   # texte principal
        "TEXT_DIM":   "#8E8E93",   # texte secondaire
        "TEXT_FAINT": "#5C5C63",   # texte tertiaire (placeholder)
        "ACCENT":     "#7C5CFF",   # violet doux
        "ACCENT_DIM": "#5B3FCC",
        "SUCCESS":    "#3FB950",
        "WARNING":    "#D29922",
        "DANGER":     "#F85149",
        "ROW_HOVER":  "#1A1A1E",
        "ROW_DRAG":   "#2A2240",   # ligne en cours de drop
    },
    "light": {
        "BG":         "#FAFAFA",
        "SURFACE":    "#FFFFFF",
        "SURFACE_2":  "#F4F4F5",
        "BORDER":     "#E4E4E7",
        "TEXT":       "#18181B",
        "TEXT_DIM":   "#71717A",
        "TEXT_FAINT": "#A1A1AA",
        "ACCENT":     "#7C5CFF",
        "ACCENT_DIM": "#5B3FCC",
        "SUCCESS":    "#16A34A",
        "WARNING":    "#CA8A04",
        "DANGER":     "#DC2626",
        "ROW_HOVER":  "#F4F4F5",
        "ROW_DRAG":   "#EDE9FE",
    },
}

# Couleurs des badges d'ordre (pastilles)
ORDER_COLORS = ["#7C5CFF", "#3FB950", "#58A6FF", "#F0883E",
                "#DB61A2", "#D29922", "#F85149", "#A371F7"]

FONT_FAMILY    = "Segoe UI"
FONT_TITLE     = (FONT_FAMILY, 18, "bold")
FONT_SUBTITLE  = (FONT_FAMILY, 11, "bold")
FONT_BODY      = (FONT_FAMILY, 10)
FONT_BODY_BOLD = (FONT_FAMILY, 10, "bold")
FONT_SMALL     = (FONT_FAMILY, 9)
FONT_MONO      = ("Cascadia Mono", 10)

# ============================================================
# WIN32 HELPERS
# ============================================================
MAPVK_VK_TO_VSC = 0x00
user32.MapVirtualKeyW.argtypes  = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype   = wintypes.UINT
user32.GetKeyNameTextW.argtypes = [wintypes.LPARAM, wintypes.LPWSTR, ctypes.c_int]
user32.GetKeyNameTextW.restype  = ctypes.c_int
user32.VkKeyScanW.argtypes      = [wintypes.WCHAR]
user32.VkKeyScanW.restype       = wintypes.SHORT

kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                 wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.QueryFullProcessImageNameW.restype  = wintypes.BOOL

class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", ctypes.c_ulong)]

MONITOR_DEFAULTTONEAREST = 2
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype  = wintypes.HANDLE
user32.GetMonitorInfoW.argtypes   = [wintypes.HANDLE, ctypes.POINTER(_MONITORINFO)]
user32.GetMonitorInfoW.restype    = wintypes.BOOL

def get_monitor_rect(hwnd):
    """Rect (left, top, right, bottom) de l'écran contenant hwnd, ou None si indisponible."""
    try:
        hmon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(_MONITORINFO)
        if hmon and user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r = mi.rcMonitor
            return (r.left, r.top, r.right, r.bottom)
    except Exception:
        pass
    return None

EXTENDED_VK = {0x21,0x22,0x23,0x24,0x25,0x26,0x27,0x28,0x2D,0x2E,0x5B,0x5C}

def vk_to_display_name(vk: int) -> str:
    try:
        sc = user32.MapVirtualKeyW(int(vk), MAPVK_VK_TO_VSC)
        if not sc:
            return f"VK_{vk}"
        if int(vk) in EXTENDED_VK:
            sc |= 0xE000
        lparam = sc << 16
        buf = ctypes.create_unicode_buffer(128)
        if user32.GetKeyNameTextW(lparam, buf, 128) > 0 and buf.value.strip():
            return buf.value
    except Exception:
        pass
    if 0x70 <= int(vk) <= 0x87:
        return f"F{int(vk) - 0x6F}"
    return f"VK_{vk}"

_VERSION_RE   = re.compile(r"^\d+(\.\d+){1,}$")
_NOISE_WORDS  = {"dofus", "release", "beta", "bêta", "alpha"}

def format_char_label(title: str) -> str:
    """Nettoie un titre de fenêtre Dofus pour l'affichage (overlay) :
    retire les segments de version (ex. 3.6.11.15) et les mentions
    inutiles (Dofus, Release…), garde le nom du perso + sa classe."""
    parts = [p.strip() for p in title.split(" - ") if p.strip()]
    cleaned = [p for p in parts
               if not _VERSION_RE.match(p) and p.lower() not in _NOISE_WORDS]
    return " - ".join(cleaned) if cleaned else title

def mods_to_display_name(mods: int) -> str:
    if not mods: return ""
    p = []
    if mods & MOD_CONTROL: p.append("Ctrl")
    if mods & MOD_ALT:     p.append("Alt")
    if mods & MOD_SHIFT:   p.append("Shift")
    if mods & MOD_WIN:     p.append("Win")
    return "+".join(p)

KEYSYM_TO_VK = {
    "Escape":0x1B,"Return":0x0D,"Tab":0x09,"space":0x20,"BackSpace":0x08,
    "Delete":0x2E,"Insert":0x2D,"Home":0x24,"End":0x23,"Prior":0x21,
    "Next":0x22,"Left":0x25,"Up":0x26,"Right":0x27,"Down":0x28,
}

def keysym_to_vk(event):
    ks = getattr(event, "keysym", "")
    ch = getattr(event, "char", "")
    if ks.startswith("F") and ks[1:].isdigit():
        n = int(ks[1:])
        if 1 <= n <= 24:
            return 0x6F + n
    if ks in KEYSYM_TO_VK:
        return KEYSYM_TO_VK[ks]
    if ch:
        vks = user32.VkKeyScanW(ch)
        if vks != -1:
            return vks & 0xFF
    return None

# ============================================================
# CONFIG
# ============================================================
class Config:
    def __init__(self):
        # Par défaut : F21 = précédent, F23 = suivant (corrigé v3)
        self.theme         = "dark"
        self.vkey_next     = VK_F23
        self.vkey_prev     = VK_F21
        self.mods_next     = 0
        self.mods_prev     = 0
        self.auto_maximize = True
        self.show_notifs   = True
        self.show_overlay  = True
        self.always_on_top = False
        self.start_windows = False
        self.direct_keys   = []
        self.load()

    def load(self):
        if not CONFIG_PATH.exists(): return
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            self.theme         = data.get("theme", "dark")
            self.vkey_next     = int(data.get("vkey_next", VK_F23))
            self.vkey_prev     = int(data.get("vkey_prev", VK_F21))
            self.mods_next     = int(data.get("mods_next", 0))
            self.mods_prev     = int(data.get("mods_prev", 0))
            self.auto_maximize = data.get("auto_maximize", True)
            self.show_notifs   = data.get("show_notifs", True)
            self.show_overlay  = data.get("show_overlay", True)
            self.always_on_top = data.get("always_on_top", False)
            self.start_windows = data.get("start_windows", False)
            self.direct_keys   = data.get("direct_keys", [])
        except Exception as e:
            log.warning("Load config error: %s", e)

    def save(self):
        try:
            CONFIG_PATH.write_text(json.dumps({
                "theme":         self.theme,
                "vkey_next":     int(self.vkey_next),
                "vkey_prev":     int(self.vkey_prev),
                "mods_next":     int(self.mods_next),
                "mods_prev":     int(self.mods_prev),
                "auto_maximize": self.auto_maximize,
                "show_notifs":   self.show_notifs,
                "show_overlay":  self.show_overlay,
                "always_on_top": self.always_on_top,
                "start_windows": self.start_windows,
                "direct_keys":   self.direct_keys,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            log.error("Save config error: %s", e)

config = Config()

# ============================================================
# LAYOUT PERSISTANT (positions par titre de fenêtre)
# ============================================================
def load_layout():
    try:
        if LAYOUT_PATH.exists():
            return json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("Load layout error: %s", e)
    return {}

def save_layout(mapping):
    try:
        LAYOUT_PATH.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.error("Save layout error: %s", e)

# ============================================================
# PRESETS D'ÉQUIPE (plusieurs dispositions nommées, sauvegardables)
# ============================================================
PRESETS_PATH = APP_DIR / "presets.json"
DEFAULT_PRESETS = {"Équipe principale": ["Exoticlozie", "Schokocafe", "Schokobun", "Schokoarc"]}

def load_presets():
    try:
        if PRESETS_PATH.exists():
            return json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("Load presets error: %s", e)
    # Premier lancement : on pré-remplit avec l'équipe habituelle de l'utilisateur.
    save_presets(DEFAULT_PRESETS)
    return dict(DEFAULT_PRESETS)

def save_presets(mapping):
    try:
        PRESETS_PATH.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.error("Save presets error: %s", e)

def extract_char_name(title):
    return title.split(" - ")[0].strip()

# ============================================================
# DEMARRAGE AVEC WINDOWS
# ============================================================
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "DofusManager"

def _startup_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" "{os.path.abspath(__file__)}"'

def is_startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as k:
            winreg.QueryValueEx(k, RUN_VALUE_NAME)
            return True
    except OSError:
        return False

def set_startup_enabled(enabled):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, RUN_VALUE_NAME, 0, winreg.REG_SZ, _startup_command())
            else:
                try:
                    winreg.DeleteValue(k, RUN_VALUE_NAME)
                except FileNotFoundError:
                    pass
    except Exception as e:
        log.error("Startup toggle error: %s", e)

# ============================================================
# SESSION STATS
# ============================================================
class SessionStats:
    def __init__(self):
        self._times  = {}    # title -> seconds
        self._counts = {}    # title -> n
        self._cur_title = None
        self._cur_start = None
        self._session_start = time.time()

    def on_focus(self, title):
        self._close()
        self._cur_title = title
        self._cur_start = time.time()
        self._counts[title] = self._counts.get(title, 0) + 1

    def _close(self):
        if self._cur_title and self._cur_start:
            self._times[self._cur_title] = (
                self._times.get(self._cur_title, 0) + time.time() - self._cur_start)
        self._cur_title = None
        self._cur_start = None

    def snapshot(self):
        out = {t: {"seconds": s, "count": self._counts.get(t,0)}
               for t, s in self._times.items()}
        if self._cur_title and self._cur_start:
            t = self._cur_title
            extra = time.time() - self._cur_start
            if t not in out:
                out[t] = {"seconds": 0, "count": self._counts.get(t,0)}
            out[t]["seconds"] += extra
        return out

    def duration(self): return time.time() - self._session_start
    def reset(self):
        self._close(); self._times.clear(); self._counts.clear()
        self._session_start = time.time()

stats = SessionStats()

# ============================================================
# WINDOW DETECTION
# ============================================================
DOFUS_PROCESS_NAMES = {"dofus.exe", "dofus3.exe", "dofus-3.exe", "dofus 3.exe"}
SELF_PID = os.getpid()

# PROCESS_QUERY_LIMITED_INFORMATION : suffisant pour lire le chemin de l'exe,
# ne donne AUCUN accès à la mémoire du processus (pas de PROCESS_VM_READ).
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

def get_process_name(pid):
    h = None
    try:
        h = win32api.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        buf = ctypes.create_unicode_buffer(260)
        size = wintypes.DWORD(260)
        if kernel32.QueryFullProcessImageNameW(int(h), 0, buf, ctypes.byref(size)):
            return pathlib.Path(buf.value).name.lower()
        return ""
    except Exception:
        return ""
    finally:
        if h:
            try:
                win32api.CloseHandle(h)
            except Exception:
                pass

def is_dofus_window(hwnd, pid):
    if pid is None or pid == SELF_PID:
        return False
    name = get_process_name(pid)
    if name in DOFUS_PROCESS_NAMES:
        return True
    # Fallback titre, mais excluant les fenêtres du programme
    title = win32gui.GetWindowText(hwnd).strip().lower()
    if "window manager" in title or "dofus manager" in title:
        return False
    return "dofus" in title

def is_window_normal(hwnd):
    if not win32gui.IsWindowVisible(hwnd):
        return False
    try:
        l, t, r, b = win32gui.GetWindowRect(hwnd)
    except Exception:
        return False
    if (r - l) < 120 or (b - t) < 60:
        return False
    ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    if ex & win32con.WS_EX_TOOLWINDOW:
        return False
    return bool(win32gui.GetWindowText(hwnd).strip())

def enum_dofus_windows():
    out = []
    def cb(hwnd, _):
        if not is_window_normal(hwnd): return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            pid = None
        if is_dofus_window(hwnd, pid):
            out.append({"hwnd": hwnd,
                        "title": win32gui.GetWindowText(hwnd).strip(),
                        "pid": pid})
    win32gui.EnumWindows(cb, None)
    return out

def focus_window(hwnd, maximize=True):
    if not win32gui.IsWindow(hwnd):
        log.warning("Focus ignoré : fenêtre invalide/fermée (hwnd=%s)", hwnd)
        return
    try:
        if maximize:
            # SW_MAXIMIZE seul suffit (fonctionne même depuis l'état minimisé) :
            # faire d'abord SW_RESTORE affiche un flash de la fenêtre à sa taille/
            # position "restaurée" précédente avant le maximize — visible et gênant
            # en multi-écran (flash centré entre les deux écrans, sous-dimensionné).
            win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        else:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

        user32.SetWindowPos(hwnd, -1, 0,0,0,0, 0x0002|0x0001|0x0010|0x0040)
        time.sleep(0.01)
        user32.SetWindowPos(hwnd, -2, 0,0,0,0, 0x0002|0x0001|0x0010|0x0040)

        fg = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        cur_tid = kernel32.GetCurrentThreadId()
        if fg_tid and fg_tid != cur_tid:
            user32.AttachThreadInput(cur_tid, fg_tid, True)
            try:
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
                user32.SetActiveWindow(hwnd)
                user32.SetFocus(hwnd)
            finally:
                user32.AttachThreadInput(cur_tid, fg_tid, False)
        else:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetActiveWindow(hwnd)
            user32.SetFocus(hwnd)

        title = win32gui.GetWindowText(hwnd)
        stats.on_focus(title)
        log.info("Focus → %s", title)
    except Exception as e:
        log.error("Focus error: %s", e)

# ============================================================
# CYCLER
# ============================================================
class WindowCycler:
    def __init__(self):
        self.order = []   # [(pos, hwnd, title), ...] trié
        self._idx = -1

    def set_order(self, items):
        self.order = sorted([x for x in items if x[0] > 0], key=lambda t: t[0])
        self._idx = -1
        log.info("Cycle order: %d windows", len(self.order))

    def _prune_dead(self):
        """Retire du cycle les fenêtres fermées entre-temps (client Dofus quitté)."""
        alive = [x for x in self.order if win32gui.IsWindow(x[1])]
        if len(alive) != len(self.order):
            log.info("Cycle: %d fenêtre(s) fermée(s) retirée(s) du cyclage",
                      len(self.order) - len(alive))
            self.order = alive
            self._idx = -1

    def _sync_to_foreground(self):
        fg = user32.GetForegroundWindow()
        for i, (_, hwnd, _) in enumerate(self.order):
            if hwnd == fg:
                self._idx = i
                return

    def next(self):
        self._prune_dead()
        if not self.order: return None
        self._sync_to_foreground()
        self._idx = (self._idx + 1) % len(self.order)
        return self.order[self._idx]

    def prev(self):
        self._prune_dead()
        if not self.order: return None
        self._sync_to_foreground()
        self._idx = (self._idx - 1) % len(self.order)
        return self.order[self._idx]

    def goto(self, i):
        self._prune_dead()
        if 0 <= i < len(self.order):
            self._idx = i
            return self.order[i]
        return None

cycler = WindowCycler()
_last_trigger = 0.0

# Callback (défini par l'App) notifié après chaque changement de fenêtre déclenché
# par un raccourci, pour afficher la superposition "Perso N · Nom". Signature: (order, title).
_cycle_notify = None

def set_cycle_notify(fn):
    global _cycle_notify
    _cycle_notify = fn

def _debounce(fn):
    global _last_trigger
    now = time.time()
    if now - _last_trigger < 0.12: return
    _last_trigger = now
    fn()

def _notify_switch(order, hwnd, title):
    if _cycle_notify and config.show_overlay:
        try:
            _cycle_notify(order, hwnd, title)
        except Exception as e:
            log.error("Overlay notify error: %s", e)

def cycle_next():
    def _do():
        n = cycler.next()
        if n:
            focus_window(n[1], config.auto_maximize)
            _notify_switch(n[0], n[1], n[2])
    _debounce(_do)

def cycle_prev():
    def _do():
        p = cycler.prev()
        if p:
            focus_window(p[1], config.auto_maximize)
            _notify_switch(p[0], p[1], p[2])
    _debounce(_do)

def cycle_direct(i):
    def _do():
        w = cycler.goto(i)
        if w:
            focus_window(w[1], config.auto_maximize)
            _notify_switch(w[0], w[1], w[2])
    _debounce(_do)

# ============================================================
# HOTKEYS THREAD
# ============================================================
class HotkeyManager:
    def __init__(self):
        self._q = queue.Queue()
        self._stop = threading.Event()
        self._t = None

    def start(self):
        if self._t and self._t.is_alive(): return
        self._stop.clear()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def stop(self):
        self._stop.set()
        try: self._q.put_nowait(("stop", None))
        except Exception: pass

    def apply(self, vn, vp, mn, mp, directs=None):
        self._q.put(("apply", {"vn":int(vn),"vp":int(vp),"mn":int(mn),"mp":int(mp),
                               "directs": directs or []}))

    def _unreg(self, n_directs):
        user32.UnregisterHotKey(None, HK_NEXT)
        user32.UnregisterHotKey(None, HK_PREV)
        for i in range(n_directs):
            user32.UnregisterHotKey(None, HK_DIRECT_BASE + i)

    def _reg(self, p):
        fmn = MOD_NOREPEAT | p["mn"] if p["mn"] else MOD_NOREPEAT
        fmp = MOD_NOREPEAT | p["mp"] if p["mp"] else MOD_NOREPEAT
        user32.RegisterHotKey(None, HK_NEXT, fmn, p["vn"])
        user32.RegisterHotKey(None, HK_PREV, fmp, p["vp"])
        for i, dk in enumerate(p["directs"]):
            vk = dk.get("vkey")
            if vk:
                fm = MOD_NOREPEAT | dk.get("mods", 0)
                user32.RegisterHotKey(None, HK_DIRECT_BASE + i, fm, int(vk))

    def _run(self):
        cur = {"vn":config.vkey_next,"vp":config.vkey_prev,
               "mn":config.mods_next,"mp":config.mods_prev,
               "directs":config.direct_keys}
        self._unreg(len(cur["directs"]))
        self._reg(cur)
        msg = wintypes.MSG()
        while not self._stop.is_set():
            try:
                while True:
                    cmd, data = self._q.get_nowait()
                    if cmd == "stop":
                        self._stop.set(); break
                    if cmd == "apply":
                        self._unreg(len(cur["directs"]))
                        cur = data
                        self._reg(cur)
            except queue.Empty:
                pass
            if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                if msg.message == WM_HOTKEY:
                    w = msg.wParam
                    if   w == HK_NEXT: cycle_next()
                    elif w == HK_PREV: cycle_prev()
                    elif w >= HK_DIRECT_BASE: cycle_direct(w - HK_DIRECT_BASE)
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.01)
        self._unreg(len(cur["directs"]))

hotkeys = HotkeyManager()

# ============================================================
# UI COMPONENTS — minimalist
# ============================================================
class FlatButton(tk.Frame):
    """Bouton minimaliste, hover discret."""
    def __init__(self, parent, text, command, theme, kind="ghost", icon=None, width=None):
        c = theme
        if kind == "primary":
            bg, fg, hover = c["ACCENT"], "#FFFFFF", c["ACCENT_DIM"]
        elif kind == "danger":
            bg, fg, hover = c["SURFACE_2"], c["DANGER"], "#3A1F23"
        else:  # ghost
            bg, fg, hover = c["SURFACE"], c["TEXT"], c["SURFACE_2"]

        super().__init__(parent, bg=bg, cursor="hand2",
                         highlightthickness=1, highlightbackground=c["BORDER"])
        self._bg, self._fg, self._hover = bg, fg, hover
        label = (f"{icon}  {text}" if icon else text)
        self._lbl = tk.Label(self, text=label, bg=bg, fg=fg,
                             font=FONT_BODY_BOLD,
                             padx=14, pady=7)
        self._lbl.pack(fill="both", expand=True)
        if width:
            self._lbl.configure(width=width)

        for w in (self, self._lbl):
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)
            w.bind("<Button-1>", lambda e: command() if command else None)

    def _on_enter(self, _):
        self.configure(bg=self._hover)
        self._lbl.configure(bg=self._hover)
    def _on_leave(self, _):
        self.configure(bg=self._bg)
        self._lbl.configure(bg=self._bg)


class IconButton(tk.Frame):
    """Petit bouton icône carré pour la toolbar."""
    def __init__(self, parent, icon, command, theme, tooltip=""):
        c = theme
        super().__init__(parent, bg=c["SURFACE"], cursor="hand2",
                         highlightthickness=1, highlightbackground=c["BORDER"])
        self._bg, self._hover = c["SURFACE"], c["SURFACE_2"]
        self._lbl = tk.Label(self, text=icon, bg=c["SURFACE"], fg=c["TEXT"],
                             font=(FONT_FAMILY, 12), padx=8, pady=6)
        self._lbl.pack()
        for w in (self, self._lbl):
            w.bind("<Enter>", lambda e: (self.configure(bg=self._hover),
                                          self._lbl.configure(bg=self._hover)))
            w.bind("<Leave>", lambda e: (self.configure(bg=self._bg),
                                          self._lbl.configure(bg=self._bg)))
            w.bind("<Button-1>", lambda e: command() if command else None)


class SearchBar(tk.Frame):
    def __init__(self, parent, theme, on_change=None):
        c = theme
        super().__init__(parent, bg=c["SURFACE"],
                         highlightthickness=1, highlightbackground=c["BORDER"])
        tk.Label(self, text="🔍", bg=c["SURFACE"], fg=c["TEXT_DIM"],
                 font=(FONT_FAMILY, 11)).pack(side="left", padx=(12,6))
        self.var = tk.StringVar()
        self.entry = tk.Entry(self, textvariable=self.var,
                              bg=c["SURFACE"], fg=c["TEXT"],
                              insertbackground=c["TEXT"],
                              relief="flat", bd=0, font=FONT_BODY)
        self.entry.pack(side="left", fill="x", expand=True, ipady=8, padx=(0,4))
        self.clear_btn = tk.Label(self, text="✕", bg=c["SURFACE"], fg=c["TEXT_FAINT"],
                                   font=(FONT_FAMILY, 10), cursor="hand2", padx=10)
        self.clear_btn.bind("<Button-1>", lambda e: self.clear())
        self.entry.bind("<Escape>", lambda e: self.clear())
        if on_change:
            self.var.trace_add("write", lambda *a: (self._toggle_clear(), on_change()))

    def _toggle_clear(self):
        if self.var.get():
            self.clear_btn.pack(side="right", padx=(0, 10))
        else:
            self.clear_btn.pack_forget()

    def clear(self):
        self.var.set("")
        self.entry.focus_set()


# ============================================================
# WINDOW LIST — drag & drop with reordering
# ============================================================
class WindowList(tk.Frame):
    """Liste custom (pas un Treeview) pour un drag&drop propre."""
    def __init__(self, parent, theme, on_change=None):
        c = theme
        super().__init__(parent, bg=c["SURFACE"])
        self.theme = c
        self.on_change = on_change

        # Canvas scrollable
        self.canvas = tk.Canvas(self, bg=c["SURFACE"], highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = tk.Frame(self.canvas, bg=c["SURFACE"])
        self._inner_id = self.canvas.create_window((0,0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                        lambda e: self.canvas.itemconfigure(self._inner_id, width=e.width))

        # Scroll molette
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)

        self.rows = []           # liste de WindowRow dans l'ordre d'affichage
        self.windows = []        # données COMPLETES : [{hwnd, title, pid, order}]
        self.filter_text = ""    # filtre de recherche courant (n'altère jamais self.windows)
        self._dragging = None    # row en cours de drag
        self._drag_offset_y = 0
        self._drop_index = None
        self._empty_lbl = None

    def _on_wheel(self, event):
        # Scroll uniquement si la souris est sur le canvas
        x, y = self.winfo_pointerxy()
        widget = self.winfo_containing(x, y)
        if widget and (widget == self.canvas or widget.winfo_toplevel() == self.winfo_toplevel()):
            try:
                if str(self.canvas.bbox("all")) != "None":
                    self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            except Exception:
                pass

    def set_windows(self, windows):
        """windows = [{hwnd, title, pid, order}, ...]"""
        # Tri : positions > 0 par ordre croissant, puis les "—" à la fin
        with_order    = [w for w in windows if w.get("order", 0) > 0]
        without_order = [w for w in windows if w.get("order", 0) <= 0]
        with_order.sort(key=lambda w: w["order"])
        self.windows = with_order + without_order
        self._render()

    def set_filter(self, text):
        """Filtre l'affichage sans jamais toucher aux données/ordres de self.windows."""
        self.filter_text = (text or "").strip().lower()
        self._render()

    def _render(self):
        for r in self.rows:
            r.destroy()
        self.rows = []
        if self._empty_lbl:
            self._empty_lbl.destroy()
            self._empty_lbl = None
        q = self.filter_text
        for i, w in enumerate(self.windows):
            if q and q not in w["title"].lower():
                continue
            row = WindowRow(self.inner, self.theme, w, i, self)
            row.pack(fill="x", pady=(0,1))
            self.rows.append(row)
        if not self.rows:
            c = self.theme
            if q:
                msg = "Aucun résultat pour cette recherche."
            elif self.windows:
                msg = "Aucune fenêtre à afficher."
            else:
                msg = "Aucune fenêtre Dofus détectée.\nLancez le jeu puis cliquez sur ⟳."
            self._empty_lbl = tk.Label(self.inner, text=msg, bg=c["SURFACE"],
                                       fg=c["TEXT_FAINT"], font=FONT_BODY, justify="center")
            self._empty_lbl.pack(pady=40)

    def get_order_map(self):
        """Retourne {hwnd: order}."""
        out = {}
        for w in self.windows:
            out[w["hwnd"]] = w.get("order", 0)
        return out

    def set_order(self, hwnd, order):
        for w in self.windows:
            if w["hwnd"] == hwnd:
                w["order"] = int(order)
                break
        self._renumber_and_render()

    def _renumber_and_render(self):
        """Trie et réaffiche."""
        self.set_windows(self.windows)
        if self.on_change:
            self.on_change()

    # ---- Drag & drop logic ----
    def start_drag(self, row, event):
        if row.data.get("order", 0) <= 0:
            return  # On ne drague que les fenêtres avec un ordre
        self._dragging = row
        self._drag_offset_y = event.y_root - row.winfo_rooty()
        row.set_dragging(True)

    def update_drag(self, event):
        if not self._dragging: return
        # Trouve la ligne sous le curseur
        y_in_canvas = event.y_root - self.canvas.winfo_rooty() + self.canvas.canvasy(0)
        target_idx = None
        for i, r in enumerate(self.rows):
            if r is self._dragging: continue
            if r.data.get("order", 0) <= 0: continue  # on n'insère pas dans les "—"
            ry = r.winfo_y()
            rh = r.winfo_height()
            if ry <= y_in_canvas <= ry + rh:
                target_idx = i
                break

        # Reset highlights
        for r in self.rows:
            r.set_drop_target(False)
        if target_idx is not None:
            self.rows[target_idx].set_drop_target(True)
            self._drop_index = target_idx
        else:
            self._drop_index = None

    def end_drag(self, event):
        if not self._dragging:
            return
        src = self._dragging
        self._dragging.set_dragging(False)
        for r in self.rows:
            r.set_drop_target(False)

        if self._drop_index is not None:
            # Réordonner : src va à la position de drop
            ordered = [w for w in self.windows if w.get("order",0) > 0]
            unordered = [w for w in self.windows if w.get("order",0) <= 0]
            src_data = src.data
            # Trouver l'index actuel et la cible parmi les ordonnés
            try:
                old_i = ordered.index(src_data)
            except ValueError:
                old_i = None
            # Le drop_index est dans self.rows (qui contient aussi unordered), reconvertir
            drop_row = self.rows[self._drop_index]
            try:
                new_i = ordered.index(drop_row.data)
            except ValueError:
                new_i = None

            if old_i is not None and new_i is not None and old_i != new_i:
                ordered.pop(old_i)
                ordered.insert(new_i, src_data)
                # Renuméroter 1..N
                for i, w in enumerate(ordered):
                    w["order"] = i + 1
                self.windows = ordered + unordered
                log.info("Reorder: %s → position %d", src_data["title"][:40], new_i+1)

        self._dragging = None
        self._drop_index = None
        self._renumber_and_render()


class WindowRow(tk.Frame):
    """Une ligne dans la liste des fenêtres."""
    def __init__(self, parent, theme, data, index, list_widget):
        c = theme
        super().__init__(parent, bg=c["SURFACE"], height=44)
        self.pack_propagate(False)
        self.theme = c
        self.data = data
        self.index = index
        self.list_widget = list_widget
        self._normal_bg = c["SURFACE"]
        self._hover_bg  = c["ROW_HOVER"]
        self._drag_bg   = c["ROW_DRAG"]

        order = data.get("order", 0)

        # Barre d'indication "fenêtre active" (mise à jour périodiquement par l'app)
        self.active_bar = tk.Frame(self, bg=c["SURFACE"], width=3)
        self.active_bar.pack(side="left", fill="y")
        self.active_bar.pack_propagate(False)

        # Handle drag
        self.handle = tk.Label(self, text="⋮⋮", bg=c["SURFACE"],
                               fg=c["TEXT_FAINT"], font=(FONT_FAMILY, 13),
                               cursor="fleur" if order > 0 else "arrow",
                               padx=10)
        self.handle.pack(side="left")

        # Badge ordre
        badge = tk.Frame(self, bg=c["SURFACE"], width=44)
        badge.pack(side="left")
        badge.pack_propagate(False)
        if order > 0:
            badge_color = ORDER_COLORS[(order-1) % len(ORDER_COLORS)]
            chip = tk.Frame(badge, bg=badge_color)
            chip.place(relx=0.5, rely=0.5, anchor="center", width=28, height=28)
            tk.Label(chip, text=str(order), bg=badge_color, fg="#FFFFFF",
                     font=FONT_BODY_BOLD).place(relx=0.5, rely=0.5, anchor="center")
        else:
            tk.Label(badge, text="—", bg=c["SURFACE"], fg=c["TEXT_FAINT"],
                     font=FONT_BODY).place(relx=0.5, rely=0.5, anchor="center")

        # Titre
        title = data.get("title", "")
        if len(title) > 60: title = title[:57] + "…"
        self.title_lbl = tk.Label(self, text=title, bg=c["SURFACE"], fg=c["TEXT"],
                                  font=FONT_BODY, anchor="w")
        self.title_lbl.pack(side="left", fill="x", expand=True, padx=8)

        # PID
        tk.Label(self, text=f"PID {data.get('pid','?')}", bg=c["SURFACE"],
                 fg=c["TEXT_FAINT"], font=FONT_SMALL).pack(side="right", padx=12)

        # Séparateur fin en bas
        sep = tk.Frame(self, bg=c["BORDER"], height=1)
        sep.place(relx=0, rely=1.0, relwidth=1, anchor="sw")

        # Events sur toute la ligne
        for w in (self, self.handle, self.title_lbl):
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)
            w.bind("<Button-3>", self._on_right_click)
            w.bind("<Double-Button-1>", self._on_double_click)

        # Drag uniquement depuis le handle si ordonné, sinon depuis toute la ligne aussi
        drag_widgets = [self.handle] if order > 0 else []
        if order > 0:
            for w in (self, self.handle, self.title_lbl):
                w.bind("<ButtonPress-1>",   self._on_drag_start)
                w.bind("<B1-Motion>",       self._on_drag_motion)
                w.bind("<ButtonRelease-1>", self._on_drag_end)

    def _set_bg(self, color):
        self.configure(bg=color)
        self.handle.configure(bg=color)
        self.title_lbl.configure(bg=color)

    def _on_enter(self, _):
        if self.list_widget._dragging is self: return
        self._set_bg(self._hover_bg)

    def _on_leave(self, _):
        if self.list_widget._dragging is self: return
        self._set_bg(self._normal_bg)

    def set_dragging(self, on):
        if on:
            self._set_bg(self._drag_bg)
        else:
            self._set_bg(self._normal_bg)

    def set_drop_target(self, on):
        if self.list_widget._dragging is self: return
        if on:
            self._set_bg(self._drag_bg)
        else:
            self._set_bg(self._normal_bg)

    def set_active(self, on):
        """Indique visuellement si cette fenêtre est actuellement au premier plan."""
        color = self.theme["ACCENT"] if on else self._normal_bg
        try:
            self.active_bar.configure(bg=color)
        except tk.TclError:
            pass  # ligne détruite entre-temps (re-render concurrent)

    def _on_drag_start(self, event):
        self.list_widget.start_drag(self, event)

    def _on_drag_motion(self, event):
        self.list_widget.update_drag(event)

    def _on_drag_end(self, event):
        self.list_widget.end_drag(event)

    def _on_double_click(self, _):
        val = simpledialog.askinteger("Position",
                                      f"Position pour :\n{self.data['title']}",
                                      minvalue=0, maxvalue=99,
                                      parent=self.winfo_toplevel())
        if val is not None:
            self.list_widget.set_order(self.data["hwnd"], val)

    def _on_right_click(self, event):
        menu = tk.Menu(self, tearoff=0,
                       bg=self.theme["SURFACE_2"], fg=self.theme["TEXT"],
                       activebackground=self.theme["ACCENT"],
                       activeforeground="#FFFFFF",
                       bd=0, relief="flat")
        menu.add_command(label="Modifier l'ordre…", command=lambda: self._on_double_click(None))
        sub = tk.Menu(menu, tearoff=0,
                      bg=self.theme["SURFACE_2"], fg=self.theme["TEXT"],
                      activebackground=self.theme["ACCENT"],
                      activeforeground="#FFFFFF")
        for v in range(1, 9):
            sub.add_command(label=f"Position {v}",
                            command=lambda vv=v: self.list_widget.set_order(self.data["hwnd"], vv))
        menu.add_cascade(label="Position rapide", menu=sub)
        menu.add_command(label="Retirer du cycle",
                         command=lambda: self.list_widget.set_order(self.data["hwnd"], 0))
        menu.add_separator()
        menu.add_command(label="Focus maintenant",
                         command=lambda: focus_window(self.data["hwnd"], config.auto_maximize))
        try: menu.tk_popup(event.x_root, event.y_root)
        finally: menu.grab_release()


# ============================================================
# STATS WINDOW
# ============================================================
class StatsWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        c = THEMES[config.theme]
        self.configure(bg=c["BG"])
        self.title("Statistiques")
        self.geometry("560x540")
        self.transient(parent)

        # Header
        header = tk.Frame(self, bg=c["BG"])
        header.pack(fill="x", padx=28, pady=(24, 8))
        tk.Label(header, text="Statistiques", bg=c["BG"], fg=c["TEXT"],
                 font=FONT_TITLE).pack(side="left")
        tk.Label(header, text="de session", bg=c["BG"], fg=c["TEXT_DIM"],
                 font=(FONT_FAMILY, 18)).pack(side="left", padx=8)

        # Durée
        snap = stats.snapshot()
        dur = stats.duration()
        h, rem = divmod(int(dur), 3600); m, s = divmod(rem, 60)
        tk.Label(self, text=f"Durée totale  ·  {h:02d}h {m:02d}m {s:02d}s",
                 bg=c["BG"], fg=c["TEXT_DIM"],
                 font=FONT_BODY).pack(padx=28, anchor="w", pady=(0, 16))

        # Container scrollable
        container = tk.Frame(self, bg=c["SURFACE"],
                             highlightthickness=1, highlightbackground=c["BORDER"])
        container.pack(fill="both", expand=True, padx=28, pady=(0, 16))

        if not snap:
            tk.Label(container, text="Aucune fenêtre encore focusée.",
                     bg=c["SURFACE"], fg=c["TEXT_DIM"],
                     font=FONT_BODY).pack(pady=40)
        else:
            total = sum(v["seconds"] for v in snap.values()) or 1
            sorted_items = sorted(snap.items(), key=lambda x: -x[1]["seconds"])
            for i, (title, data) in enumerate(sorted_items):
                row = tk.Frame(container, bg=c["SURFACE"])
                row.pack(fill="x", padx=16, pady=10)

                # Title + chip count
                top = tk.Frame(row, bg=c["SURFACE"])
                top.pack(fill="x")
                shortt = title if len(title) <= 50 else title[:47] + "…"
                tk.Label(top, text=shortt, bg=c["SURFACE"], fg=c["TEXT"],
                         font=FONT_BODY_BOLD, anchor="w").pack(side="left")
                tk.Label(top, text=f"{data['count']} focus",
                         bg=c["SURFACE"], fg=c["TEXT_FAINT"],
                         font=FONT_SMALL).pack(side="right")

                # Bar + time
                pct = data["seconds"] / total
                th, tr = divmod(int(data["seconds"]), 3600); tm, ts = divmod(tr, 60)
                bot = tk.Frame(row, bg=c["SURFACE"])
                bot.pack(fill="x", pady=(6, 0))

                bar_bg = tk.Frame(bot, bg=c["BORDER"], height=4)
                bar_bg.pack(side="left", fill="x", expand=True)
                bar_bg.pack_propagate(False)
                self.after(50, lambda b=bar_bg, p=pct, col=ORDER_COLORS[i % len(ORDER_COLORS)]:
                           self._draw_bar(b, p, col))

                tk.Label(bot,
                         text=f"  {th:02d}h{tm:02d}m{ts:02d}s · {pct*100:.0f}%",
                         bg=c["SURFACE"], fg=c["TEXT_DIM"],
                         font=FONT_SMALL).pack(side="right")

        # Boutons
        btns = tk.Frame(self, bg=c["BG"])
        btns.pack(fill="x", padx=28, pady=(0, 24))
        FlatButton(btns, "Réinitialiser", self._reset, c, kind="danger").pack(side="left")
        FlatButton(btns, "Fermer", self.destroy, c).pack(side="right")

    def _draw_bar(self, parent, pct, color):
        w = parent.winfo_width()
        if w <= 1:
            self.after(50, lambda: self._draw_bar(parent, pct, color))
            return
        fill = tk.Frame(parent, bg=color, height=4, width=max(2, int(w * pct)))
        fill.place(x=0, y=0)

    def _reset(self):
        if messagebox.askyesno("Réinitialiser",
                               "Effacer toutes les statistiques ?", parent=self):
            stats.reset()
            self.destroy()

# ============================================================
# OPTIONS WINDOW
# ============================================================
class OptionsWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        c = THEMES[config.theme]
        self.theme = c

        self.d_next  = int(config.vkey_next)
        self.d_prev  = int(config.vkey_prev)
        self.d_mn    = int(config.mods_next)
        self.d_mp    = int(config.mods_prev)

        self.title("Paramètres")
        self.geometry("560x780")
        self.minsize(520, 600)
        self.configure(bg=c["BG"])
        self.transient(parent)
        self.grab_set()

        # Header
        h = tk.Frame(self, bg=c["BG"])
        h.pack(fill="x", padx=28, pady=(24, 16))
        tk.Label(h, text="Paramètres", bg=c["BG"], fg=c["TEXT"],
                 font=FONT_TITLE).pack(anchor="w")

        # Scroll
        canvas = tk.Canvas(self, bg=c["BG"], highlightthickness=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(28, 0))
        sb.pack(side="right", fill="y", padx=(0, 12))
        frame = tk.Frame(canvas, bg=c["BG"])
        canvas.create_window((0,0), window=frame, anchor="nw")
        frame.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(canvas.find_all()[0], width=e.width-16))

        self._section(frame, "Raccourcis principaux")
        self._build_hotkey(frame, "next", "Fenêtre suivante")
        self._build_hotkey(frame, "prev", "Fenêtre précédente")

        self._section(frame, "Raccourcis directs", pad_top=24)
        self._build_direct_keys(frame)

        self._section(frame, "Apparence", pad_top=24)
        self._build_theme(frame)

        self._section(frame, "Comportement", pad_top=24)
        self._build_behavior(frame)

        tk.Label(frame, text="Les changements sont sauvegardés automatiquement.",
                 bg=c["BG"], fg=c["TEXT_FAINT"],
                 font=FONT_SMALL).pack(anchor="w", pady=(24, 24))

        self.bind("<Escape>", lambda e: self.destroy())

    def _section(self, parent, title, pad_top=0):
        tk.Label(parent, text=title.upper(), bg=self.theme["BG"],
                 fg=self.theme["TEXT_FAINT"],
                 font=(FONT_FAMILY, 9, "bold")).pack(anchor="w", pady=(pad_top, 8))

    def _build_hotkey(self, parent, kind, label):
        c = self.theme
        card = tk.Frame(parent, bg=c["SURFACE"],
                        highlightthickness=1, highlightbackground=c["BORDER"])
        card.pack(fill="x", pady=(0, 8))

        tk.Label(card, text=label, bg=c["SURFACE"], fg=c["TEXT"],
                 font=FONT_BODY_BOLD).pack(anchor="w", padx=16, pady=(14, 4))

        # Modificateurs
        mods_frame = tk.Frame(card, bg=c["SURFACE"])
        mods_frame.pack(fill="x", padx=16, pady=(0, 8))
        cur_mods = getattr(self, f"d_m{'n' if kind=='next' else 'p'}")
        ctrl = tk.BooleanVar(value=bool(cur_mods & MOD_CONTROL))
        alt  = tk.BooleanVar(value=bool(cur_mods & MOD_ALT))
        shift= tk.BooleanVar(value=bool(cur_mods & MOD_SHIFT))
        win_ = tk.BooleanVar(value=bool(cur_mods & MOD_WIN))
        setattr(self, f"ctrl_{kind}", ctrl)
        setattr(self, f"alt_{kind}", alt)
        setattr(self, f"shift_{kind}", shift)
        setattr(self, f"win_{kind}", win_)
        for txt, v in [("Ctrl",ctrl),("Alt",alt),("Shift",shift),("Win",win_)]:
            cb = tk.Checkbutton(mods_frame, text=txt, variable=v,
                                bg=c["SURFACE"], fg=c["TEXT"],
                                selectcolor=c["SURFACE_2"],
                                activebackground=c["SURFACE"],
                                activeforeground=c["TEXT"],
                                font=FONT_SMALL, bd=0,
                                command=lambda k=kind: self._save_mods(k))
            cb.pack(side="left", padx=(0, 14))

        # Touche
        kf = tk.Frame(card, bg=c["SURFACE"])
        kf.pack(fill="x", padx=16, pady=(0, 14))
        key_lbl = tk.Label(kf, text=vk_to_display_name(getattr(self, f"d_{kind}")),
                           bg=c["SURFACE_2"], fg=c["TEXT"], font=FONT_BODY_BOLD,
                           padx=14, pady=6, width=14, anchor="center")
        key_lbl.pack(side="left")
        setattr(self, f"key_lbl_{kind}", key_lbl)
        FlatButton(kf, "Modifier", lambda k=kind: self._bind_key(k), c).pack(side="left", padx=8)

    def _build_direct_keys(self, parent):
        c = self.theme
        card = tk.Frame(parent, bg=c["SURFACE"],
                        highlightthickness=1, highlightbackground=c["BORDER"])
        card.pack(fill="x", pady=(0, 8))

        tk.Label(card, text="Une touche par personnage (optionnel)",
                 bg=c["SURFACE"], fg=c["TEXT_DIM"],
                 font=FONT_SMALL).pack(anchor="w", padx=16, pady=(14, 8))

        self._direct_rows_widgets = []
        self._direct_container = tk.Frame(card, bg=c["SURFACE"])
        self._direct_container.pack(fill="x", padx=16, pady=(0, 8))

        n = max(len(config.direct_keys), 4)
        for i in range(n):
            self._add_direct_row(i)

        FlatButton(card, "+ Ajouter", lambda: self._add_direct_row(len(self._direct_rows_widgets)),
                   c).pack(anchor="w", padx=16, pady=(0, 14))

    def _add_direct_row(self, idx):
        c = self.theme
        dk = config.direct_keys[idx] if idx < len(config.direct_keys) else {}
        vkey = dk.get("vkey")
        row = tk.Frame(self._direct_container, bg=c["SURFACE"])
        row.pack(fill="x", pady=3)

        tk.Label(row, text=f"Perso {idx+1}",
                 bg=c["SURFACE"], fg=c["TEXT_DIM"],
                 font=FONT_BODY, width=10, anchor="w").pack(side="left")

        lbl = tk.Label(row, text=vk_to_display_name(int(vkey)) if vkey else "—",
                       bg=c["SURFACE_2"], fg=c["TEXT"], font=FONT_BODY_BOLD,
                       padx=12, pady=5, width=12, anchor="center")
        lbl.pack(side="left", padx=(0, 8))

        FlatButton(row, "Modifier", lambda i=idx, l=lbl: self._bind_direct(i, l), c).pack(side="left", padx=4)
        FlatButton(row, "✕", lambda i=idx, l=lbl: self._clear_direct(i, l), c, kind="danger").pack(side="left")

        self._direct_rows_widgets.append({"vkey": vkey, "label": lbl})

    def _bind_direct(self, idx, label):
        self._capture_key(lambda vk: self._on_direct_captured(idx, label, vk),
                          f"Raccourci direct — Perso {idx+1}")

    def _on_direct_captured(self, idx, label, vk):
        label.config(text=vk_to_display_name(vk))
        if idx < len(self._direct_rows_widgets):
            self._direct_rows_widgets[idx]["vkey"] = vk
        self._save_direct()

    def _clear_direct(self, idx, label):
        label.config(text="—")
        if idx < len(self._direct_rows_widgets):
            self._direct_rows_widgets[idx]["vkey"] = None
        self._save_direct()

    def _save_direct(self):
        config.direct_keys = [{"vkey": r["vkey"], "mods": 0}
                              for r in self._direct_rows_widgets if r["vkey"]]
        config.save()
        hotkeys.apply(config.vkey_next, config.vkey_prev,
                     config.mods_next, config.mods_prev, config.direct_keys)
        self.parent._refresh_footer()

    def _build_theme(self, parent):
        c = self.theme
        card = tk.Frame(parent, bg=c["SURFACE"],
                        highlightthickness=1, highlightbackground=c["BORDER"])
        card.pack(fill="x", pady=(0, 8))
        wrap = tk.Frame(card, bg=c["SURFACE"])
        wrap.pack(fill="x", padx=16, pady=14)
        FlatButton(wrap, "Sombre", lambda: self._set_theme("dark"), c,
                   kind="primary" if config.theme=="dark" else "ghost").pack(side="left", padx=(0,8))
        FlatButton(wrap, "Clair", lambda: self._set_theme("light"), c,
                   kind="primary" if config.theme=="light" else "ghost").pack(side="left")

    def _set_theme(self, name):
        config.theme = name
        config.save()
        self.parent._apply_theme_and_rebuild()
        self.destroy()

    def _build_behavior(self, parent):
        c = self.theme
        card = tk.Frame(parent, bg=c["SURFACE"],
                        highlightthickness=1, highlightbackground=c["BORDER"])
        card.pack(fill="x", pady=(0, 8))

        self.mx_var  = tk.BooleanVar(value=config.auto_maximize)
        self.nt_var  = tk.BooleanVar(value=config.show_notifs)
        self.ov_var  = tk.BooleanVar(value=config.show_overlay)
        self.top_var = tk.BooleanVar(value=config.always_on_top)
        self.su_var  = tk.BooleanVar(value=is_startup_enabled())

        def on_change():
            config.auto_maximize = self.mx_var.get()
            config.show_notifs   = self.nt_var.get()
            config.show_overlay  = self.ov_var.get()
            config.always_on_top = self.top_var.get()
            config.save()
            self.parent.attributes("-topmost", config.always_on_top)

        def on_startup_change():
            set_startup_enabled(self.su_var.get())
            config.start_windows = self.su_var.get()
            config.save()

        def cb(text, var, cmd):
            tk.Checkbutton(card, text=text, variable=var, bg=c["SURFACE"], fg=c["TEXT"],
                           selectcolor=c["SURFACE_2"], activebackground=c["SURFACE"],
                           activeforeground=c["TEXT"], font=FONT_BODY, bd=0,
                           command=cmd).pack(anchor="w", padx=16, pady=(6, 0))

        cb("Maximiser les fenêtres au focus", self.mx_var, on_change)
        cb("Afficher les notifications", self.nt_var, on_change)
        cb("Afficher un aperçu à l'écran au changement de fenêtre", self.ov_var, on_change)
        cb("Toujours au premier plan (fenêtre du manager)", self.top_var, on_change)
        cb("Démarrer avec Windows", self.su_var, on_startup_change)
        tk.Frame(card, bg=c["SURFACE"], height=10).pack()

    def _bind_key(self, kind):
        self._capture_key(lambda vk, evt=None: self._on_key_captured(kind, vk, evt),
                          "Appuyez sur une touche", capture_mods=True)

    def _on_key_captured(self, kind, vk, event=None):
        if event is not None:
            detected = 0
            if event.state & 0x0004:  detected |= MOD_CONTROL
            if event.state & 0x20000: detected |= MOD_ALT
            if event.state & 0x0001:  detected |= MOD_SHIFT
            if detected:
                getattr(self, f"ctrl_{kind}").set(bool(detected & MOD_CONTROL))
                getattr(self, f"alt_{kind}").set(bool(detected & MOD_ALT))
                getattr(self, f"shift_{kind}").set(bool(detected & MOD_SHIFT))
        setattr(self, f"d_{kind}", int(vk))
        getattr(self, f"key_lbl_{kind}").config(text=vk_to_display_name(int(vk)))
        if kind == "next": config.vkey_next = int(vk)
        else:              config.vkey_prev = int(vk)
        config.save()
        self._save_mods(kind)

    def _save_mods(self, kind):
        mods = 0
        if getattr(self, f"ctrl_{kind}").get():  mods |= MOD_CONTROL
        if getattr(self, f"alt_{kind}").get():   mods |= MOD_ALT
        if getattr(self, f"shift_{kind}").get(): mods |= MOD_SHIFT
        if getattr(self, f"win_{kind}").get():   mods |= MOD_WIN
        if kind == "next": config.mods_next = mods
        else:              config.mods_prev = mods
        setattr(self, f"d_m{'n' if kind=='next' else 'p'}", mods)
        config.save()
        hotkeys.apply(config.vkey_next, config.vkey_prev,
                     config.mods_next, config.mods_prev, config.direct_keys)
        self.parent._refresh_footer()

    def _capture_key(self, callback, title, capture_mods=False):
        c = self.theme
        w = tk.Toplevel(self)
        w.title(title); w.geometry("380x140"); w.resizable(False, False)
        w.configure(bg=c["BG"]); w.transient(self); w.grab_set()
        tk.Label(w, text=title, bg=c["BG"], fg=c["TEXT"],
                 font=FONT_BODY_BOLD).pack(pady=(28, 4))
        tk.Label(w, text="Échap pour annuler", bg=c["BG"], fg=c["TEXT_FAINT"],
                 font=FONT_SMALL).pack()
        def on_key(event):
            if event.keysym == "Escape":
                w.destroy(); return
            vk = keysym_to_vk(event)
            if vk is None: return
            if capture_mods:
                callback(vk, event)
            else:
                callback(vk)
            w.destroy()
        w.bind("<KeyPress>", on_key); w.focus_force()


# ============================================================
# PRESETS WINDOW — plusieurs dispositions d'équipe sauvegardées
# ============================================================
class PresetsWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        c = THEMES[config.theme]
        self.theme = c
        self.configure(bg=c["BG"])
        self.title("Presets d'équipe")
        self.geometry("480x520")
        self.minsize(420, 360)
        self.transient(parent)

        header = tk.Frame(self, bg=c["BG"])
        header.pack(fill="x", padx=24, pady=(24, 8))
        tk.Label(header, text="Presets d'équipe", bg=c["BG"], fg=c["TEXT"],
                 font=FONT_TITLE).pack(side="left")

        tk.Label(self, text="Enregistrez une disposition de fenêtres (ordre 1, 2, 3…) "
                            "et ré-appliquez-la en un clic, même après avoir relancé Dofus.",
                 bg=c["BG"], fg=c["TEXT_DIM"], font=FONT_SMALL, wraplength=420,
                 justify="left").pack(fill="x", padx=24, pady=(0, 12), anchor="w")

        self.list_container = tk.Frame(self, bg=c["SURFACE"],
                                       highlightthickness=1, highlightbackground=c["BORDER"])
        self.list_container.pack(fill="both", expand=True, padx=24, pady=(0, 12))

        self._render_list()

        btns = tk.Frame(self, bg=c["BG"])
        btns.pack(fill="x", padx=24, pady=(0, 24))
        FlatButton(btns, "+ Enregistrer la disposition actuelle", self._save_current,
                  c, kind="primary").pack(side="left")
        FlatButton(btns, "Fermer", self.destroy, c).pack(side="right")

        self.bind("<Escape>", lambda e: self.destroy())

    def _render_list(self):
        for w in self.list_container.winfo_children():
            w.destroy()
        c = self.theme
        presets = self.parent._presets
        if not presets:
            tk.Label(self.list_container, text="Aucun preset enregistré pour l'instant.",
                     bg=c["SURFACE"], fg=c["TEXT_FAINT"], font=FONT_BODY).pack(pady=40)
            return
        for name in list(presets.keys()):
            names = presets[name]
            row = tk.Frame(self.list_container, bg=c["SURFACE"])
            row.pack(fill="x", padx=14, pady=10)

            tk.Label(row, text=name, bg=c["SURFACE"], fg=c["TEXT"],
                     font=FONT_BODY_BOLD, anchor="w").pack(fill="x")

            preview = " → ".join(names)
            if len(preview) > 52: preview = preview[:49] + "…"
            tk.Label(row, text=preview, bg=c["SURFACE"], fg=c["TEXT_FAINT"],
                     font=FONT_SMALL, anchor="w").pack(fill="x", pady=(2, 8))

            actions = tk.Frame(row, bg=c["SURFACE"])
            actions.pack(fill="x")
            FlatButton(actions, "Appliquer", lambda n=name: self._apply(n),
                      c, kind="primary").pack(side="left", padx=(0, 6))
            FlatButton(actions, "Renommer", lambda n=name: self._rename(n),
                      c).pack(side="left", padx=(0, 6))
            FlatButton(actions, "Supprimer", lambda n=name: self._delete(n),
                      c, kind="danger").pack(side="left")

            tk.Frame(self.list_container, bg=c["BORDER"], height=1).pack(fill="x")

    def _apply(self, name):
        names = self.parent._presets.get(name, [])
        matched, total = self.parent._apply_char_list(names)
        if config.show_notifs:
            self.parent._toast(f"« {name} » appliqué ({matched}/{total} détecté(s)).")

    def _rename(self, name):
        new_name = simpledialog.askstring("Renommer le preset", "Nouveau nom :",
                                          initialvalue=name, parent=self)
        if not new_name: return
        new_name = new_name.strip()
        if not new_name or new_name == name: return
        if new_name in self.parent._presets:
            messagebox.showerror("Erreur", f"Un preset « {new_name} » existe déjà.", parent=self)
            return
        self.parent._presets[new_name] = self.parent._presets.pop(name)
        save_presets(self.parent._presets)
        self._render_list()

    def _delete(self, name):
        if messagebox.askyesno("Supprimer", f"Supprimer le preset « {name} » ?", parent=self):
            self.parent._presets.pop(name, None)
            save_presets(self.parent._presets)
            self._render_list()

    def _save_current(self):
        ordered = sorted([w for w in self.parent.wlist.windows if w.get("order", 0) > 0],
                         key=lambda w: w["order"])
        if not ordered:
            messagebox.showwarning("Aucune position",
                                   "Définissez d'abord un ordre (positions 1, 2, 3…) sur les\n"
                                   "fenêtres à inclure dans ce preset.", parent=self)
            return
        name = simpledialog.askstring("Enregistrer le preset", "Nom du preset :", parent=self)
        if not name: return
        name = name.strip()
        if not name: return
        if name in self.parent._presets:
            if not messagebox.askyesno("Écraser",
                                       f"Un preset « {name} » existe déjà. L'écraser ?",
                                       parent=self):
                return
        names = [extract_char_name(w["title"]) for w in ordered]
        self.parent._presets[name] = names
        save_presets(self.parent._presets)
        self._render_list()
        if config.show_notifs:
            self.parent._toast(f"Preset « {name} » enregistré.")


# ============================================================
# MAIN APP
# ============================================================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Dofus 3 — Window Manager")
        self.geometry("980x680")
        self.minsize(820, 560)

        self._icon_img  = None
        self._tray_icon = None
        self._overlay_win = None
        self._order_applied = False
        self._last_pos_txt = ""
        self._layout = load_layout()
        self._presets = load_presets()
        self._load_icon()

        self._apply_theme()
        self._build()
        self._refresh()
        self.attributes("-topmost", config.always_on_top)

        hotkeys.start()
        self.after(200, lambda: hotkeys.apply(
            config.vkey_next, config.vkey_prev,
            config.mods_next, config.mods_prev, config.direct_keys))
        set_cycle_notify(lambda order, hwnd, title:
                         self.after(0, lambda o=order, h=hwnd, t=title: self._show_switch_overlay(o, h, t)))

        if _HAS_TRAY:
            self._start_tray()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._schedule_auto_refresh()
        self._schedule_highlight_tick()
        log.info("App started")

    # ---- Theme ----
    def _apply_theme(self):
        self.c = THEMES.get(config.theme, THEMES["dark"])
        self.configure(bg=self.c["BG"])

    def _apply_theme_and_rebuild(self):
        for w in self.winfo_children(): w.destroy()
        self._apply_theme()
        self._build()
        self._refresh()

    def _load_icon(self):
        try:
            if _HAS_PIL and ICON_PATH.exists():
                img = Image.open(ICON_PATH).convert("RGBA").resize((28, 28), Image.LANCZOS)
                self._icon_img = ImageTk.PhotoImage(img)
        except Exception as e:
            log.warning("Icon load error: %s", e)

    # ---- Tray ----
    def _start_tray(self):
        try:
            if _HAS_PIL and ICON_PATH.exists():
                img = Image.open(ICON_PATH).resize((64,64))
            else:
                img = Image.new("RGB", (64,64), color="#7C5CFF")
            menu = pystray.Menu(
                TrayItem("Ouvrir", self._show_from_tray, default=True),
                TrayItem("Statistiques", lambda i,it: self.after(0, lambda: StatsWindow(self))),
                pystray.Menu.SEPARATOR,
                TrayItem("Quitter", self._quit_from_tray),
            )
            self._tray_icon = pystray.Icon("DofusManager", img, "Dofus Manager", menu)
            threading.Thread(target=self._tray_icon.run, daemon=True).start()
        except Exception as e:
            log.warning("Tray error: %s", e)

    def _show_from_tray(self, icon=None, item=None):
        self.after(0, self.deiconify); self.after(0, self.lift)

    def _quit_from_tray(self, icon=None, item=None):
        self.after(0, self._quit)

    def _on_close(self):
        if self._tray_icon: self.withdraw()
        else: self._quit()

    def _quit(self):
        hotkeys.stop()
        if self._tray_icon:
            try: self._tray_icon.stop()
            except Exception: pass
        log.info("App stopped"); self.destroy()

    # ---- UI ----
    def _build(self):
        c = self.c

        # === Sidebar / Topbar minimaliste ===
        topbar = tk.Frame(self, bg=c["BG"])
        topbar.pack(fill="x", padx=24, pady=(20, 4))

        # Logo + nom
        left = tk.Frame(topbar, bg=c["BG"])
        left.pack(side="left")
        if self._icon_img:
            tk.Label(left, image=self._icon_img, bg=c["BG"]).pack(side="left", padx=(0, 10))
        tk.Label(left, text="Dofus Manager", bg=c["BG"], fg=c["TEXT"],
                 font=FONT_TITLE).pack(side="left")
        tk.Label(left, text="·  v3", bg=c["BG"], fg=c["TEXT_FAINT"],
                 font=(FONT_FAMILY, 11)).pack(side="left", padx=(8, 0))

        # Boutons droite
        right = tk.Frame(topbar, bg=c["BG"])
        right.pack(side="right")
        IconButton(right, "⟳", self._refresh, c).pack(side="left", padx=4)
        IconButton(right, "📊", lambda: StatsWindow(self), c).pack(side="left", padx=4)
        IconButton(right, "⚙",  lambda: OptionsWindow(self), c).pack(side="left", padx=4)

        # === Sub header ===
        sub = tk.Frame(self, bg=c["BG"])
        sub.pack(fill="x", padx=24, pady=(0, 12))
        tk.Label(sub, text="Fenêtres Dofus détectées",
                 bg=c["BG"], fg=c["TEXT_DIM"], font=FONT_BODY).pack(side="left")
        self.count_lbl = tk.Label(sub, text="", bg=c["BG"], fg=c["TEXT_FAINT"],
                                  font=FONT_SMALL)
        self.count_lbl.pack(side="left", padx=8)

        # === Toolbar (search + actions) ===
        tbar = tk.Frame(self, bg=c["BG"])
        tbar.pack(fill="x", padx=24, pady=(0, 12))

        self.search = SearchBar(tbar, c, on_change=self._on_search)
        self.search.pack(side="left", fill="x", expand=True, padx=(0, 8))

        FlatButton(tbar, "Appliquer", self._apply_order, c, kind="primary").pack(side="left", padx=(0, 6))
        FlatButton(tbar, "Presets", lambda: PresetsWindow(self), c, icon="⭐").pack(side="left", padx=(0, 6))
        FlatButton(tbar, "Réinitialiser", self._reset_order, c).pack(side="left", padx=(0, 6))
        FlatButton(tbar, "Exporter", self._export, c).pack(side="left", padx=(0, 6))
        FlatButton(tbar, "Importer", self._import, c).pack(side="left")

        # === Liste ===
        list_card = tk.Frame(self, bg=c["SURFACE"],
                             highlightthickness=1, highlightbackground=c["BORDER"])
        list_card.pack(fill="both", expand=True, padx=24, pady=(0, 16))

        # En-tête colonnes
        hdr = tk.Frame(list_card, bg=c["SURFACE"], height=36)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="", bg=c["SURFACE"], width=4).pack(side="left", padx=10)
        tk.Label(hdr, text="ORDRE", bg=c["SURFACE"], fg=c["TEXT_FAINT"],
                 font=(FONT_FAMILY, 8, "bold"), width=6).pack(side="left", padx=2)
        tk.Label(hdr, text="FENÊTRE", bg=c["SURFACE"], fg=c["TEXT_FAINT"],
                 font=(FONT_FAMILY, 8, "bold"), anchor="w").pack(side="left", fill="x", expand=True, padx=8)
        tk.Label(hdr, text="PID", bg=c["SURFACE"], fg=c["TEXT_FAINT"],
                 font=(FONT_FAMILY, 8, "bold")).pack(side="right", padx=20)
        tk.Frame(list_card, bg=c["BORDER"], height=1).pack(fill="x")

        # Hint
        hint = tk.Frame(list_card, bg=c["SURFACE"])
        hint.pack(fill="x", pady=(8, 0))
        tk.Label(hint, text="↕  Glissez les lignes pour réordonner  ·  Double-clic pour définir une position",
                 bg=c["SURFACE"], fg=c["TEXT_FAINT"], font=FONT_SMALL).pack(padx=16, anchor="w")

        # La liste elle-même
        self.wlist = WindowList(list_card, c, on_change=self._on_list_change)
        self.wlist.pack(fill="both", expand=True, padx=8, pady=8)

        # === Footer ===
        footer = tk.Frame(self, bg=c["BG"], height=44)
        footer.pack(fill="x", side="bottom"); footer.pack_propagate(False)
        fc = tk.Frame(footer, bg=c["BG"]); fc.pack(fill="both", expand=True, padx=28)
        tk.Label(fc, text="© Subs12 · 2025", bg=c["BG"], fg=c["TEXT_FAINT"],
                 font=FONT_SMALL).pack(side="left", pady=12)
        self.footer_lbl = tk.Label(fc, bg=c["BG"], fg=c["TEXT_DIM"],
                                   font=FONT_SMALL)
        self.footer_lbl.pack(side="right", pady=12)
        self._refresh_footer()

    def _refresh_footer(self, pos_txt=None):
        if pos_txt is None:
            pos_txt = self._last_pos_txt
        else:
            self._last_pos_txt = pos_txt
        nk = vk_to_display_name(config.vkey_next)
        pk = vk_to_display_name(config.vkey_prev)
        nm = mods_to_display_name(config.mods_next)
        pm = mods_to_display_name(config.mods_prev)
        nd = f"{nm}+{nk}" if nm else nk
        pd = f"{pm}+{pk}" if pm else pk
        txt = f"{pd}  ←  Précédent     ·     Suivant  →  {nd}"
        if config.direct_keys:
            parts = [vk_to_display_name(int(d["vkey"]))
                     for d in config.direct_keys if d.get("vkey")]
            if parts:
                txt += "     ·     " + " / ".join(f"P{i+1}:{k}" for i,k in enumerate(parts))
        if pos_txt:
            txt = f"Position {pos_txt}     ·     " + txt
        self.footer_lbl.config(text=txt)

    # ---- Data ----
    def _refresh(self, wins_override=None):
        wins = wins_override if wins_override is not None else enum_dofus_windows()
        # On garde l'ordre existant si déjà connu, sinon on restaure depuis le layout
        # persistant (association par titre de fenêtre — survit à un relance de Dofus).
        existing = {w["hwnd"]: w.get("order", 0) for w in self.wlist.windows} \
                   if hasattr(self, "wlist") else {}
        data = []
        for w in wins:
            order = existing.get(w["hwnd"], 0)
            if order <= 0:
                order = int(self._layout.get(w["title"], 0))
            w["order"] = order
            data.append(w)
        self.wlist.set_windows(data)
        self.count_lbl.config(text=f"· {len(wins)} fenêtre{'s' if len(wins)>1 else ''}")
        log.info("Refresh: %d Dofus windows", len(wins))
        # Si un cyclage était déjà actif, on le resynchronise silencieusement
        # (nouveau perso ouvert / fermé pendant la session).
        if self._order_applied:
            self._apply_order(silent=True)

    def _schedule_auto_refresh(self):
        self.after(2500, self._auto_refresh_tick)

    def _auto_refresh_tick(self):
        try:
            if not self.search.var.get().strip():
                wins = enum_dofus_windows()
                cur_hwnds = {w["hwnd"] for w in wins}
                known_hwnds = {w["hwnd"] for w in self.wlist.windows}
                if cur_hwnds != known_hwnds:
                    self._refresh(wins_override=wins)
        except Exception as e:
            log.error("Auto-refresh error: %s", e)
        finally:
            self._schedule_auto_refresh()

    def _schedule_highlight_tick(self):
        self.after(500, self._highlight_tick)

    def _highlight_tick(self):
        try:
            self._update_active_highlight()
        except Exception as e:
            log.debug("Highlight tick error: %s", e)
        finally:
            self._schedule_highlight_tick()

    def _update_active_highlight(self):
        try:
            fg = user32.GetForegroundWindow()
        except Exception:
            fg = None
        for row in self.wlist.rows:
            row.set_active(row.data.get("hwnd") == fg)
        pos_txt = ""
        if cycler.order:
            idx = next((i for i, (_, h, _) in enumerate(cycler.order) if h == fg), None)
            pos_txt = f"{idx+1}/{len(cycler.order)}" if idx is not None else f"–/{len(cycler.order)}"
        if pos_txt != self._last_pos_txt:
            self._refresh_footer(pos_txt)

    # ---- Superposition de changement de fenêtre ----
    def _show_switch_overlay(self, order, hwnd, title):
        try:
            if self._overlay_win is not None:
                self._overlay_win.destroy()
        except Exception:
            pass
        self._overlay_win = None
        try:
            c = self.c
            ov = tk.Toplevel(self)
            self._overlay_win = ov
            ov.overrideredirect(True)
            ov.attributes("-topmost", True)
            try:
                ov.attributes("-alpha", 0.94)
            except Exception:
                pass
            ov.configure(bg=c["ACCENT"])
            frame = tk.Frame(ov, bg=c["SURFACE"], highlightthickness=2,
                             highlightbackground=c["ACCENT"])
            frame.pack(padx=2, pady=2)
            row = tk.Frame(frame, bg=c["SURFACE"])
            row.pack(padx=22, pady=16)
            badge_color = ORDER_COLORS[(order - 1) % len(ORDER_COLORS)] if order else c["ACCENT"]
            chip = tk.Frame(row, bg=badge_color, width=42, height=42)
            chip.pack(side="left", padx=(0, 14))
            chip.pack_propagate(False)
            tk.Label(chip, text=str(order) if order else "•", bg=badge_color, fg="#FFFFFF",
                     font=(FONT_FAMILY, 16, "bold")).place(relx=0.5, rely=0.5, anchor="center")
            label = format_char_label(title)
            shortt = label if len(label) <= 42 else label[:39] + "…"
            tk.Label(row, text=shortt, bg=c["SURFACE"], fg=c["TEXT"],
                     font=(FONT_FAMILY, 14, "bold")).pack(side="left")

            ov.update_idletasks()
            w = ov.winfo_reqwidth()
            mon = get_monitor_rect(hwnd) if hwnd else None
            if mon:
                left, top, right, _ = mon
                x = left + (right - left - w) // 2
                y = top + 20
            else:
                sw = ov.winfo_screenwidth()
                x = (sw - w) // 2
                y = 20
            ov.geometry(f"+{x}+{y}")
            ov.after(900, self._destroy_overlay)
        except Exception as e:
            log.error("Overlay error: %s", e)

    def _destroy_overlay(self):
        if self._overlay_win is not None:
            try:
                self._overlay_win.destroy()
            except Exception:
                pass
            self._overlay_win = None

    # ---- Toast (notification non bloquante) ----
    def _toast(self, text, ms=2200):
        c = self.c
        t = tk.Toplevel(self)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        t.configure(bg=c["ACCENT"])
        tk.Label(t, text=text, bg=c["ACCENT"], fg="#FFFFFF",
                font=FONT_BODY_BOLD, padx=18, pady=10).pack()
        self.update_idletasks()
        x = self.winfo_rootx() + self.winfo_width() - t.winfo_reqwidth() - 32
        y = self.winfo_rooty() + self.winfo_height() - t.winfo_reqheight() - 56
        t.geometry(f"+{max(x,0)}+{max(y,0)}")
        t.after(ms, t.destroy)

    def _on_search(self):
        # Filtre purement visuel : self.wlist.windows (données + ordres) n'est jamais tronqué.
        q = self.search.var.get().strip().lower()
        self.wlist.set_filter(q)
        total = len(self.wlist.windows)
        if q:
            visible = len(self.wlist.rows)
            self.count_lbl.config(text=f"· {visible}/{total} résultat{'s' if visible>1 else ''}")
        else:
            self.count_lbl.config(text=f"· {total} fenêtre{'s' if total>1 else ''}")

    def _on_list_change(self):
        # Appelé après chaque réordonnancement : on persiste le layout par titre
        # pour pouvoir le restaurer automatiquement (ex. après relance de Dofus).
        self._layout = {w["title"]: w["order"] for w in self.wlist.windows
                        if w.get("order", 0) > 0}
        save_layout(self._layout)

    def _apply_order(self, silent=False):
        items = [(int(w.get("order", 0)), w["hwnd"], w["title"])
                 for w in self.wlist.windows]
        cycler.set_order(items)
        n = len(cycler.order)
        if n == 0:
            self._order_applied = False
            if not silent:
                messagebox.showwarning("Aucune fenêtre",
                                       "Définissez une position (1, 2, 3…) sur au moins\n"
                                       "une fenêtre Dofus avant d'appliquer.",
                                       parent=self)
            return
        self._order_applied = True
        if not silent and config.show_notifs:
            self._toast(f"{n} fenêtre(s) configurée(s) pour le cyclage.")

    def _apply_char_list(self, names):
        """Applique un ordre de cyclage à partir d'une liste de noms de personnages
        (ordonnée). Retourne (nb_trouvés, nb_total). Utilisé par les presets."""
        favs = [n.strip().lower() for n in names if n.strip()]
        if not favs:
            return 0, 0
        by_name = {}
        for w in self.wlist.windows:
            by_name.setdefault(extract_char_name(w["title"]).lower(), w)
        for w in self.wlist.windows:
            w["order"] = 0
        matched = 0
        for i, fav in enumerate(favs, start=1):
            w = by_name.get(fav)
            if w:
                w["order"] = i
                matched += 1
        self.wlist.set_windows(self.wlist.windows)
        self._on_list_change()
        self._apply_order(silent=True)
        return matched, len(favs)

    def _reset_order(self):
        if not messagebox.askyesno("Réinitialiser l'ordre",
                                   "Retirer toutes les fenêtres du cyclage ?",
                                   parent=self):
            return
        for w in self.wlist.windows:
            w["order"] = 0
        self.wlist.set_windows(self.wlist.windows)
        cycler.set_order([])
        self._order_applied = False
        self._layout = {}
        save_layout(self._layout)
        if config.show_notifs:
            self._toast("Cyclage réinitialisé.")

    def _export(self):
        fp = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON","*.json"), ("Tous","*.*")],
            title="Exporter")
        if not fp: return
        data = {w["title"]: w.get("order", 0) for w in self.wlist.windows
                if w.get("order", 0) > 0}
        try:
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            if config.show_notifs:
                self._toast(f"Exporté vers {pathlib.Path(fp).name}")
        except Exception as e:
            messagebox.showerror("Erreur", str(e), parent=self)

    def _import(self):
        fp = filedialog.askopenfilename(
            filetypes=[("JSON","*.json"), ("Tous","*.*")],
            title="Importer")
        if not fp: return
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            imported = 0
            for w in self.wlist.windows:
                if w["title"] in data:
                    w["order"] = int(data[w["title"]])
                    imported += 1
            self.wlist.set_windows(self.wlist.windows)
            self._on_list_change()
            if config.show_notifs:
                self._toast(f"{imported} fenêtre(s) importée(s).")
        except Exception as e:
            messagebox.showerror("Erreur", str(e), parent=self)


# ============================================================
# MAIN
# ============================================================
_MUTEX_NAME = "Global\\DofusManager_SingleInstance_Mutex"

def _acquire_single_instance():
    """Empêche deux instances simultanées (double enregistrement des raccourcis globaux)."""
    handle = win32event.CreateMutex(None, False, _MUTEX_NAME)
    already_running = (win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS)
    return handle, already_running

if __name__ == "__main__":
    _mutex_handle, _already_running = _acquire_single_instance()
    if _already_running:
        log.warning("Une instance de Dofus Manager tourne déjà — arrêt.")
        try:
            _root = tk.Tk(); _root.withdraw()
            messagebox.showwarning("Dofus Manager",
                                   "Dofus Manager est déjà lancé.\n"
                                   "Regardez la zone de notification (system tray).")
            _root.destroy()
        except Exception:
            pass
        sys.exit(0)

    app = App()
    app.mainloop()
