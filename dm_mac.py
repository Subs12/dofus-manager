# -*- coding: utf-8 -*-
"""Dofus Manager — couche macOS (Accessibility + Quartz).

Même interface que dm_win.py. Aucune interaction avec la mémoire du jeu : les fenêtres
sont listées, affichées et déplacées via l'API d'accessibilité de macOS, les raccourcis
globaux passent par un « event tap » Quartz. Les deux nécessitent l'autorisation
Réglages Système › Confidentialité et sécurité › Accessibilité.

Codes de touches : les « vk » stockés sont ici les codes matériels macOS (kVK_*), pas les
virtual-keys Windows. Les boutons de souris gardent les mêmes pseudo-codes (MOUSE_VK_BASE).
"""
import ctypes
import fcntl
import math
import os
import pathlib
import plistlib
import queue
import subprocess
import sys
import threading
import time

import AppKit
import objc
import Quartz
from ApplicationServices import (AXIsProcessTrusted, AXIsProcessTrustedWithOptions,
                                 AXUIElementCopyAttributeValue, AXUIElementCreateApplication,
                                 AXUIElementPerformAction, AXUIElementSetAttributeValue,
                                 AXUIElementSetMessagingTimeout, AXValueCreate, AXValueGetValue,
                                 kAXTrustedCheckOptionPrompt, kAXValueCGPointType,
                                 kAXValueCGSizeType)

import dm_core as core

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000  # MOD_WIN = ⌘

MOUSE_VK_BASE = 0x10000
MOUSE_X1  = MOUSE_VK_BASE | 1   # bouton 4 (arrière)
MOUSE_X2  = MOUSE_VK_BASE | 2   # bouton 5 (avant)
MOUSE_MID = MOUSE_VK_BASE | 3   # clic molette
_MOUSE_NAMES = {MOUSE_X1: "Souris 4", MOUSE_X2: "Souris 5", MOUSE_MID: "Clic molette"}
_MOUSE_BUTTONS = {2: MOUSE_MID, 3: MOUSE_X1, 4: MOUSE_X2}   # kCGMouseEventButtonNumber -> pseudo-vk
_MOUSE_EXTRA = 0x10   # boutons supplémentaires (souris gaming : Corsair, Razer…) : n° macOS + 0x10


def _mouse_vk_of(button):
    """Pseudo-vk d'un bouton « autre » (n° macOS ≥ 2) : 4/5/molette, puis tous les suivants."""
    button = int(button)
    if button in _MOUSE_BUTTONS:
        return _MOUSE_BUTTONS[button]
    return MOUSE_VK_BASE | (_MOUSE_EXTRA + button) if button >= 5 else None

# Les claviers Mac n'ont ni F21 ni F23 : par défaut, boutons latéraux de la souris.
DEFAULT_NEXT, DEFAULT_PREV = MOUSE_X2, MOUSE_X1
STARTUP_LABEL = "Ouvrir à la connexion"
TRAY_LABEL = "barre des menus"
SHORTCUT_MOD = "Command"
SHORTCUT_MOD_NAME = "⌘"
HAS_TURN_WATCH = False   # macOS n'expose pas le rebond d'icône du Dock d'une autre app

_KC_ESCAPE, _KC_BACKSPACE = 0x35, 0x33


def is_mouse_vk(vk):
    return bool(int(vk or 0) & MOUSE_VK_BASE)


def enable_dpi_awareness():
    pass  # Retina géré nativement par Tk


# ============================================================
# AUTORISATION ACCESSIBILITÉ
# ============================================================
def accessibility_trusted(prompt=False):
    try:
        if prompt:
            return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}))
        return bool(AXIsProcessTrusted())
    except Exception:
        return False


def open_accessibility_settings():
    subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"])


# ============================================================
# TOUCHES
# ============================================================
_SPECIAL_NAMES = {
    0x24: "Entrée", 0x30: "Tab", 0x31: "Espace", 0x33: "Retour arrière", 0x35: "Échap",
    0x75: "Suppr", 0x73: "Début", 0x77: "Fin", 0x74: "Page ↑", 0x79: "Page ↓", 0x72: "Insert",
    0x7B: "←", 0x7C: "→", 0x7D: "↓", 0x7E: "↑", 0x4C: "Entrée (pavé)", 0x47: "Clear",
    0x7A: "F1", 0x78: "F2", 0x63: "F3", 0x76: "F4", 0x60: "F5", 0x61: "F6", 0x62: "F7",
    0x64: "F8", 0x65: "F9", 0x6D: "F10", 0x67: "F11", 0x6F: "F12", 0x69: "F13", 0x6B: "F14",
    0x71: "F15", 0x6A: "F16", 0x40: "F17", 0x4F: "F18", 0x50: "F19", 0x5A: "F20",
    0x52: "Pavé 0", 0x53: "Pavé 1", 0x54: "Pavé 2", 0x55: "Pavé 3", 0x56: "Pavé 4",
    0x57: "Pavé 5", 0x58: "Pavé 6", 0x59: "Pavé 7", 0x5B: "Pavé 8", 0x5C: "Pavé 9",
    0x41: "Pavé .", 0x43: "Pavé *", 0x45: "Pavé +", 0x4E: "Pavé -", 0x4B: "Pavé /", 0x51: "Pavé =",
}
_MODIFIER_KEYCODES = {0x37, 0x36, 0x38, 0x3C, 0x3A, 0x3D, 0x3B, 0x3E, 0x39, 0x3F}


def _layout_key_names():
    """Caractère produit par chaque touche dans la disposition clavier courante (AZERTY…).

    Calculé une fois, au chargement du module (thread principal : les API TIS l'exigent).
    """
    names = {}
    try:
        carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        carbon.TISCopyCurrentKeyboardLayoutInputSource.restype = ctypes.c_void_p
        carbon.TISGetInputSourceProperty.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        carbon.TISGetInputSourceProperty.restype = ctypes.c_void_p
        carbon.LMGetKbdType.restype = ctypes.c_uint8
        carbon.UCKeyTranslate.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint16, ctypes.c_uint32,
                                          ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
                                          ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                                          ctypes.POINTER(ctypes.c_uint16)]
        cf.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]
        cf.CFDataGetBytePtr.restype = ctypes.c_void_p
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        src = carbon.TISCopyCurrentKeyboardLayoutInputSource()
        if not src:
            return names
        try:
            prop = ctypes.c_void_p.in_dll(carbon, "kTISPropertyUnicodeKeyLayoutData")
            data = carbon.TISGetInputSourceProperty(src, prop)
            if not data:
                return names
            layout = cf.CFDataGetBytePtr(data)
            kbd = carbon.LMGetKbdType()
            for code in range(0x80):
                if code in _SPECIAL_NAMES or code in _MODIFIER_KEYCODES:
                    continue
                dead = ctypes.c_uint32(0)
                buf = (ctypes.c_uint16 * 8)()
                n = ctypes.c_ulong(0)
                # action 3 = kUCKeyActionDisplay, option 1 = sans touches mortes (« ^ » affiché tel quel)
                if carbon.UCKeyTranslate(layout, code, 3, 0, kbd, 1, ctypes.byref(dead), 8,
                                         ctypes.byref(n), buf) == 0 and n.value:
                    ch = "".join(chr(c) for c in buf[:n.value]).strip()
                    if ch and ch.isprintable():
                        names[code] = ch.upper()
        finally:
            cf.CFRelease(src)
    except Exception as e:
        core.log.debug("Noms des touches : %s", e)
    return names


_KEY_NAMES = _layout_key_names()


def vk_name(vk):
    vk = int(vk)
    if is_mouse_vk(vk):
        n = vk & 0xFF
        return _MOUSE_NAMES.get(vk) or (f"Souris {n - _MOUSE_EXTRA + 1}" if n >= _MOUSE_EXTRA else f"Souris {n}")
    return _SPECIAL_NAMES.get(vk) or _KEY_NAMES.get(vk) or f"Touche {vk}"


def mods_name(mods):
    parts = []
    if mods & MOD_CONTROL: parts.append("Ctrl")
    if mods & MOD_ALT:     parts.append("Option")
    if mods & MOD_SHIFT:   parts.append("Maj")
    if mods & MOD_WIN:     parts.append("Cmd")
    return "+".join(parts)


def _mods_from_flags(flags):
    m = 0
    if flags & Quartz.kCGEventFlagMaskControl:   m |= MOD_CONTROL
    if flags & Quartz.kCGEventFlagMaskAlternate: m |= MOD_ALT
    if flags & Quartz.kCGEventFlagMaskShift:     m |= MOD_SHIFT
    if flags & Quartz.kCGEventFlagMaskCommand:   m |= MOD_WIN
    return m


def current_mods():
    return _mods_from_flags(Quartz.CGEventSourceFlagsState(Quartz.kCGEventSourceStateCombinedSessionState))


_MODIFIER_KEYSYMS = {"Control_L", "Control_R", "Alt_L", "Alt_R", "Shift_L", "Shift_R", "Meta_L", "Meta_R",
                     "Super_L", "Super_R", "Option_L", "Option_R", "Command_L", "Command_R", "Caps_Lock"}


def event_to_combo(event):
    """(code, mods) depuis un événement clavier Tk (repli quand l'event tap n'est pas actif).
    Tk/macOS : le code matériel est dans les 8 bits de poids fort de keycode."""
    if getattr(event, "keysym", "") in _MODIFIER_KEYSYMS:
        return None
    code = (int(getattr(event, "keycode", 0) or 0) >> 24) & 0xFF
    if code in _MODIFIER_KEYCODES:
        return None
    mods = 0
    if event.state & 0x0004: mods |= MOD_CONTROL
    if event.state & 0x0010: mods |= MOD_ALT
    if event.state & 0x0001: mods |= MOD_SHIFT
    if event.state & 0x0008: mods |= MOD_WIN
    return code, mods


# ============================================================
# ÉCRANS (coordonnées globales, origine en haut à gauche de l'écran principal — comme AX et Tk)
# ============================================================
_monitors_cache = []


def _is_main_thread():
    return threading.current_thread() is threading.main_thread()


def list_monitors():
    """AppKit n'est sollicité que depuis le thread principal ; ailleurs, dernier relevé."""
    global _monitors_cache
    if not _is_main_thread() and _monitors_cache:
        return [dict(m) for m in _monitors_cache]
    mons = []
    try:
        screens = list(AppKit.NSScreen.screens() or [])
        if screens:
            ph = screens[0].frame().size.height

            def conv(r):
                x, y, w, h = r.origin.x, r.origin.y, r.size.width, r.size.height
                top = ph - (y + h)
                return (int(x), int(top), int(x + w), int(top + h))
            for i, s in enumerate(screens):
                mons.append({"rect": conv(s.frame()), "work": conv(s.visibleFrame()), "primary": i == 0})
    except Exception as e:
        core.log.error("Écrans : %s", e)
    if mons:
        _monitors_cache = mons
    return [dict(m) for m in mons]


list_monitors()  # amorce le cache depuis le thread principal


def _monitor_for_point(x, y):
    mons = list_monitors()
    for m in mons:
        l, t, r, b = m["rect"]
        if l <= x < r and t <= y < b:
            return m
    return mons[0] if mons else None


def get_monitor_rect(hwnd):
    fr = _frame(hwnd)
    if not fr:
        return None
    x, y, w, h = fr
    m = _monitor_for_point(x + w / 2, y + h / 2)
    return m["rect"] if m else None


# ============================================================
# DÉMARRAGE À LA CONNEXION (LaunchAgent utilisateur)
# ============================================================
_AGENT_LABEL = "com.subs12.dofusmanager"
_AGENT_PATH = pathlib.Path.home() / "Library" / "LaunchAgents" / f"{_AGENT_LABEL}.plist"


def _bundle_path():
    """Chemin du .app si l'appli tourne depuis un bundle, sinon None."""
    p = pathlib.Path(sys.executable).resolve()
    for parent in p.parents:
        if parent.suffix == ".app":
            return parent
    return None


def _startup_command():
    bundle = _bundle_path() if getattr(sys, "frozen", False) else None
    if bundle:
        return ["/usr/bin/open", "-a", str(bundle)]
    return [sys.executable, os.path.abspath(sys.argv[0])]


def is_startup_enabled():
    return _AGENT_PATH.exists()


def set_startup_enabled(enabled):
    try:
        if enabled:
            _AGENT_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(_AGENT_PATH, "wb") as f:
                plistlib.dump({"Label": _AGENT_LABEL, "ProgramArguments": _startup_command(),
                               "RunAtLoad": True, "ProcessType": "Interactive"}, f)
        else:
            _AGENT_PATH.unlink(missing_ok=True)
    except Exception as e:
        core.log.error("Ouverture à la connexion : %s", e)


# ============================================================
# DÉTECTION DES FENÊTRES
# ============================================================
SELF_PID = os.getpid()

_libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
_libproc.proc_listallpids.argtypes = [ctypes.c_void_p, ctypes.c_int]
_libproc.proc_listallpids.restype = ctypes.c_int
_libproc.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
_libproc.proc_pidpath.restype = ctypes.c_int

_hiservices = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
_AXGetWindow = _hiservices._AXUIElementGetWindow   # AXUIElement -> CGWindowID (API privée stable)
_AXGetWindow.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
_AXGetWindow.restype = ctypes.c_int32

_AX_TIMEOUT = 0.6   # un client figé (chargement) ne doit pas bloquer les raccourcis


def _all_pids():
    n = _libproc.proc_listallpids(None, 0)
    if n <= 0:
        return []
    buf = (ctypes.c_int * (n + 64))()
    n = _libproc.proc_listallpids(buf, ctypes.sizeof(buf))
    return [p for p in buf[:max(n, 0)] if p > 0]


def get_process_name(pid):
    buf = ctypes.create_string_buffer(4096)
    try:
        if _libproc.proc_pidpath(int(pid), buf, 4096) > 0:
            return os.path.basename(buf.value.decode("utf-8", "replace")).lower()
    except Exception:
        pass
    return ""


def is_dofus_process(pid):
    # Par nom d'exécutable, comme sous Windows (Dofus.app/Contents/MacOS/Dofus).
    if not pid or pid == SELF_PID:
        return False
    name = get_process_name(pid)
    return name.startswith("dofus") and "manager" not in name and "helper" not in name


_lock = threading.RLock()
_windows = {}    # CGWindowID -> (pid, AXUIElement)
_apps = {}       # pid -> AXUIElement de l'application


def _app_elem(pid):
    with _lock:
        app = _apps.get(pid)
        if app is None:
            app = AXUIElementCreateApplication(pid)
            AXUIElementSetMessagingTimeout(app, _AX_TIMEOUT)
            _apps[pid] = app
        return app


def _attr(elem, name):
    try:
        err, val = AXUIElementCopyAttributeValue(elem, name, None)
        return val if err == 0 else None
    except Exception:
        return None


def _set(elem, name, value):
    try:
        return AXUIElementSetAttributeValue(elem, name, value) == 0
    except Exception:
        return False


def _wid_of(elem):
    wid = ctypes.c_uint32(0)
    try:
        if _AXGetWindow(objc.pyobjc_id(elem), ctypes.byref(wid)) == 0:
            return int(wid.value)
    except Exception:
        pass
    return 0


def enum_dofus_windows():
    out, seen_pids = [], set()
    for pid in _all_pids():
        if not is_dofus_process(pid):
            continue
        seen_pids.add(pid)
        app = _app_elem(pid)
        # Le client Unity de Dofus renvoie une liste AXWindows vide : sa fenêtre n'est
        # accessible que via AXMainWindow / AXFocusedWindow.
        wins = list(_attr(app, "AXWindows") or [])
        if not wins:
            wins = [w for w in (_attr(app, "AXMainWindow"), _attr(app, "AXFocusedWindow")) if w is not None]
        seen_wids = set()
        for w in wins:
            try:
                sub = _attr(w, "AXSubrole")
                if sub and sub not in ("AXStandardWindow", "AXDialog"):
                    continue
                title = str(_attr(w, "AXTitle") or "").strip()
                wid = _wid_of(w)
                if not title or not wid or wid in seen_wids:
                    continue
                seen_wids.add(wid)
                with _lock:
                    _windows[wid] = (pid, w)
                name, klass = core.split_title(title)
                out.append({"hwnd": wid, "pid": pid, "title": title, "name": name, "klass": klass})
            except Exception:
                pass
    with _lock:  # oublie les processus fermés
        for pid in [p for p in _apps if p not in seen_pids]:
            _apps.pop(pid, None)
        for wid in [k for k, (p, _) in _windows.items() if p not in seen_pids]:
            _windows.pop(wid, None)
    return out


def _lookup(hwnd):
    with _lock:
        entry = _windows.get(hwnd)
    if entry is None:
        enum_dofus_windows()
        with _lock:
            entry = _windows.get(hwnd)
    return entry


def is_window(hwnd):
    entry = _lookup(hwnd) if hwnd else None
    if not entry:
        return False
    try:
        err, _ = AXUIElementCopyAttributeValue(entry[1], "AXRole", None)
    except Exception:
        return False
    if err in (-25202, -25201):   # kAXErrorInvalidUIElement / IllegalArgument : fenêtre fermée
        with _lock:
            _windows.pop(hwnd, None)
        return False
    return True


def window_title(hwnd):
    entry = _lookup(hwnd) if hwnd else None
    return str(_attr(entry[1], "AXTitle") or "") if entry else ""


def get_foreground_window():
    """CGWindowID de la fenêtre au premier plan (liste Quartz triée de l'avant vers l'arrière).

    Un client Dofus possède aussi de petites fenêtres annexes (barres de 33 px) : si la
    première fenêtre appartient à un processus Dofus connu, on renvoie sa fenêtre de jeu.
    """
    try:
        lst = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID) or []
        for d in lst:
            if d.get("kCGWindowLayer") == 0:
                wid, pid = int(d.get("kCGWindowNumber") or 0), d.get("kCGWindowOwnerPID")
                with _lock:
                    if wid in _windows:
                        return wid
                    game = next((w for w, (p, _) in _windows.items() if p == pid), None)
                return game or wid
    except Exception:
        pass
    return 0


def _frame(hwnd):
    entry = _lookup(hwnd) if hwnd else None
    if not entry:
        return None
    pos, size = _attr(entry[1], "AXPosition"), _attr(entry[1], "AXSize")
    if pos is None or size is None:
        return None
    try:
        _, p = AXValueGetValue(pos, kAXValueCGPointType, None)
        _, s = AXValueGetValue(size, kAXValueCGSizeType, None)
        return p.x, p.y, s.width, s.height
    except Exception:
        return None


def _set_frame(elem, x, y, w, h):
    # Taille, position, puis taille : une fenêtre trop grande pour l'ancienne position est
    # rognée par le système au premier réglage.
    size = AXValueCreate(kAXValueCGSizeType, Quartz.CGSize(w, h))
    _set(elem, "AXSize", size)
    _set(elem, "AXPosition", AXValueCreate(kAXValueCGPointType, Quartz.CGPoint(x, y)))
    _set(elem, "AXSize", size)


def _fill_work_area(hwnd, elem, monitor=None):
    if _attr(elem, "AXFullScreen"):   # plein écran natif (Space dédié) : on n'y touche pas
        return
    if monitor is None:
        fr = _frame(hwnd)
        if not fr:
            return
        monitor = _monitor_for_point(fr[0] + fr[2] / 2, fr[1] + fr[3] / 2)
        if not monitor:
            return
        l, t, r, b = monitor["work"]
        if abs(fr[0] - l) <= 2 and abs(fr[1] - t) <= 2 and abs(fr[2] - (r - l)) <= 2 and abs(fr[3] - (b - t)) <= 2:
            return   # déjà « maximisée »
    l, t, r, b = monitor["work"]
    _set_frame(elem, l, t, r - l, b - t)


def _activate_pid(pid):
    _set(_app_elem(pid), "AXFrontmost", True)
    try:
        app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is not None and not app.isActive():
            app.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
    except Exception:
        pass


def focus_window(hwnd, maximize=True):
    entry = _lookup(hwnd) if hwnd else None
    if not entry or not is_window(hwnd):
        core.log.warning("Focus ignoré : fenêtre fermée (id=%s)", hwnd)
        return False
    pid, elem = entry
    try:
        if _attr(elem, "AXMinimized"):
            _set(elem, "AXMinimized", False)
        if maximize:
            _fill_work_area(hwnd, elem)
        AXUIElementPerformAction(elem, "AXRaise")
        _set(elem, "AXMain", True)
        _activate_pid(pid)
        core.stats.on_focus(core.char_name(str(_attr(elem, "AXTitle") or "")))
        return True
    except Exception as e:
        core.log.error("Focus error: %s", e)
        return False


# ============================================================
# DISPOSITION DES FENÊTRES (mosaïque / multi-écrans)
# ============================================================
def arrange_windows(hwnds, mode, monitor_index=0):
    """mode : 'single' (tous en plein écran sur un écran), 'grid' (mosaïque sur un écran),
    'spread' (un perso par écran), 'maximize' (plein écran là où ils sont)."""
    entries = [(h, _lookup(h)) for h in hwnds if is_window(h)]
    entries = [(h, e[1]) for h, e in entries if e]
    mons = list_monitors()
    if not entries or not mons:
        return 0
    try:
        for _, elem in entries:
            if _attr(elem, "AXMinimized"):
                _set(elem, "AXMinimized", False)
        if mode == "grid":
            left, top, right, bottom = mons[min(monitor_index, len(mons) - 1)]["work"]
            cols = math.ceil(math.sqrt(len(entries)))
            rows = math.ceil(len(entries) / cols)
            cw, ch = (right - left) // cols, (bottom - top) // rows
            for i, (_, elem) in enumerate(entries):
                r, c = divmod(i, cols)
                _set_frame(elem, left + c * cw, top + r * ch, cw, ch)
        elif mode == "single":
            mon = mons[min(monitor_index, len(mons) - 1)]
            for h, elem in entries:
                _fill_work_area(h, elem, mon)
        elif mode == "spread":
            for i, (h, elem) in enumerate(entries):
                _fill_work_area(h, elem, mons[i % len(mons)])
        elif mode == "maximize":
            for h, elem in entries:
                _fill_work_area(h, elem)
    except Exception as e:
        core.log.error("Disposition : %s", e)
    core.log.info("Disposition %s : %d fenêtres", mode, len(entries))
    return len(entries)


# ============================================================
# EVENT TAP (clavier + boutons de souris, avec interception)
# ============================================================
_KEY_EVENTS = (Quartz.kCGEventKeyDown, Quartz.kCGEventKeyUp)
_MOUSE_EVENTS = (Quartz.kCGEventOtherMouseDown, Quartz.kCGEventOtherMouseUp)
_TAP_MASK = 0
for _t in _KEY_EVENTS + _MOUSE_EVENTS:
    _TAP_MASK |= Quartz.CGEventMaskBit(_t)


class _EventTap:
    """Event tap Quartz sur son propre thread (CFRunLoop). handler(kind, code, mods, is_down,
    is_repeat) -> True pour intercepter l'événement. kind : 'key' ou 'mouse'.
    Le rappel doit rendre la main vite : sinon macOS désactive le tap (réactivé ici)."""

    def __init__(self, handler):
        self._handler = handler
        self._tap = None
        self._loop = None
        self._ready = threading.Event()
        self._cb_ref = self._cb   # référence gardée pour PyObjC

    @property
    def active(self):
        return self._tap is not None

    def start(self):
        if self._tap is not None:
            return True
        self._ready.clear()
        threading.Thread(target=self._run, daemon=True).start()
        self._ready.wait(2)
        return self._tap is not None

    def stop(self):
        tap, loop = self._tap, self._loop
        self._tap = self._loop = None
        if tap is not None:
            try:
                Quartz.CGEventTapEnable(tap, False)
            except Exception:
                pass
        if loop is not None:
            Quartz.CFRunLoopStop(loop)

    def _run(self):
        tap = Quartz.CGEventTapCreate(Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
                                      Quartz.kCGEventTapOptionDefault, _TAP_MASK, self._cb_ref, None)
        if not tap:
            self._ready.set()
            return
        loop = Quartz.CFRunLoopGetCurrent()
        src = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        Quartz.CFRunLoopAddSource(loop, src, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(tap, True)
        self._tap, self._loop = tap, loop
        self._ready.set()
        Quartz.CFRunLoopRun()
        Quartz.CFRunLoopRemoveSource(loop, src, Quartz.kCFRunLoopCommonModes)

    def _cb(self, proxy, etype, event, refcon):
        try:
            if etype in (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput):
                if self._tap is not None:
                    Quartz.CGEventTapEnable(self._tap, True)
                return event
            mods = _mods_from_flags(Quartz.CGEventGetFlags(event))
            if etype in _KEY_EVENTS:
                code = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
                rep = bool(Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventAutorepeat))
                if self._handler("key", int(code), mods, etype == Quartz.kCGEventKeyDown, rep):
                    return None
            elif etype in _MOUSE_EVENTS:
                btn = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGMouseEventButtonNumber)
                vk = _mouse_vk_of(btn)
                if vk and self._handler("mouse", vk, mods, etype == Quartz.kCGEventOtherMouseDown, False):
                    return None
        except Exception as e:
            core.log.error("Event tap : %s", e)
        return event


class MouseCapture:
    """Capte la prochaine touche ou le prochain bouton 4/5/molette, pour l'assignation d'un
    raccourci. Sous macOS, le clavier passe aussi par ici : on obtient le code matériel exact,
    même pour une touche déjà liée à un raccourci. Échap et Retour arrière restent à Tk."""

    def __init__(self):
        self.result = None
        self._tap = _EventTap(self._press)

    def start(self):
        self.result = None
        return self._tap.start()

    def stop(self):
        self._tap.stop()

    def _press(self, kind, code, mods, is_down, is_repeat):
        if kind == "key" and (code in (_KC_ESCAPE, _KC_BACKSPACE) and not mods):
            return False
        if is_down and self.result is None:
            self.result = (code, mods)
        return True   # toujours consommé : ne doit pas atteindre la fenêtre derrière


# ============================================================
# RACCOURCIS GLOBAUX
# ============================================================
class HotkeyManager:
    """Un event tap intercepte les combinaisons liées ; les actions sont exécutées sur un
    thread à part (le rappel du tap doit rester instantané)."""

    def __init__(self):
        self._tap = _EventTap(self._on_event)
        self._lock = threading.Lock()
        self._binds = {}          # (code, mods) -> action
        self._swallowed = set()   # (kind, code) dont l'appui a été intercepté
        self._spec = None
        self._jobs = queue.Queue()
        self._started = False
        self.paused = False

    def start(self, spec):
        if self._started:
            return
        self._started = True
        self._spec = spec
        threading.Thread(target=self._dispatch, daemon=True).start()
        core.log.info("Autorisation Accessibilité : %s", "oui" if accessibility_trusted() else "non")
        self._ensure_tap()
        self._rebind()
        if not self._tap.active:
            threading.Thread(target=self._wait_permission, daemon=True).start()

    def _ensure_tap(self):
        if not self._tap.active and accessibility_trusted():
            self._tap.start()
        return self._tap.active

    def _wait_permission(self):
        """L'autorisation Accessibilité peut être accordée pendant que l'appli tourne."""
        core.events.put(("permission", False))
        while self._started and not self._tap.active:
            time.sleep(2)
            if self._ensure_tap():
                core.log.info("Autorisation Accessibilité accordée : raccourcis actifs.")
                core.events.put(("permission", True))
                self._rebind()

    def apply(self, spec):
        self._spec = spec
        self._rebind()

    def set_paused(self, paused):
        self.paused = paused
        self._rebind()

    def stop(self):
        self._started = False
        self._tap.stop()
        self._jobs.put(None)

    def _rebind(self):
        spec = self._spec
        if spec is None:
            return
        binds, entries = {}, [(spec["next"], ("step", +1), "Suivant"), (spec["prev"], ("step", -1), "Précédent")]
        entries += [((vk, mods), ("target", target), core.target_label(target))
                    for vk, mods, target in spec["directs"]]
        entries += [((vk, mods), ("preset", name), f"Preset {name}") for vk, mods, name in spec.get("presets", [])]
        failed = []
        for (vk, mods), action, label in entries:
            if not vk:
                continue
            key = (int(vk), int(mods))
            if not self._tap.active or key in binds:
                failed.append(f"{label} ({core.combo_name(vk, mods)})")
                continue
            binds[key] = action
        with self._lock:
            self._binds = {} if self.paused else binds
        if failed:
            core.log.warning("Raccourcis non enregistrés : %s", failed)
        core.events.put(("hotkeys", [] if self.paused else failed))

    def _on_event(self, kind, code, mods, is_down, is_repeat):
        if not is_down:
            if (kind, code) in self._swallowed:
                # Jamais un relâchement orphelin : le jeu resterait « touche enfoncée ».
                self._swallowed.discard((kind, code))
                return True
            return False
        with self._lock:
            action = self._binds.get((code, mods))
        if action is None:
            return False
        if kind == "mouse" and core.config.mouse_passthrough:
            self._jobs.put(action)
            return False
        if not is_repeat:   # équivalent de MOD_NOREPEAT
            self._jobs.put(action)
        self._swallowed.add((kind, code))
        return True

    def _dispatch(self):
        while True:
            action = self._jobs.get()
            if action is None:
                break
            try:
                core.run_action(action)
            except Exception as e:
                core.log.error("Hotkey dispatch error: %s", e)


# ============================================================
# TOUR DE JEU — non disponible sous macOS
# ============================================================
class TurnWatcher:
    def start(self):
        pass

    def stop(self):
        pass


# ============================================================
# INSTANCE UNIQUE
# ============================================================
_lock_file = None


def acquire_single_instance():
    global _lock_file
    try:
        _lock_file = open(core.APP_DIR / "instance.lock", "w")
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def listen_show_requests(on_request, root=None):
    """Clic sur l'icône du Dock ou 2e ouverture du .app : macOS envoie « reopen » à l'instance."""
    if root is not None:
        try:
            root.createcommand("::tk::mac::ReopenApplication", on_request)
        except Exception as e:
            core.log.debug("ReopenApplication : %s", e)


def signal_running_instance():
    return False


def open_folder(path):
    subprocess.Popen(["open", str(path)])


# ============================================================
# FENÊTRES FLOTTANTES (overlay, toasts)
# ============================================================
def _nswindow(tk_win):
    """NSWindow d'une fenêtre Tk, retrouvée par un titre temporaire unique."""
    ns = getattr(tk_win, "_dm_ns", None)
    if ns is not None:
        return ns
    try:
        tk_win.update_idletasks()
        old = tk_win.title()
        token = f"dm-float-{id(tk_win)}"
        tk_win.title(token)
        tk_win.update_idletasks()
        for w in AppKit.NSApp.windows():
            if str(w.title()) == token:
                ns = w
                break
        tk_win.title(old)
    except Exception as e:
        core.log.debug("NSWindow : %s", e)
    if ns is not None:
        ns.setIgnoresMouseEvents_(True)
        ns.setHidesOnDeactivate_(False)
        ns.setLevel_(AppKit.NSStatusWindowLevel)
        # Visible sur tous les Spaces, y compris au-dessus d'un Dofus en plein écran natif.
        ns.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces |
                                  AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary |
                                  AppKit.NSWindowCollectionBehaviorStationary |
                                  AppKit.NSWindowCollectionBehaviorIgnoresCycle)
        tk_win._dm_ns = ns
    return ns


def make_click_through(tk_win):
    """Fenêtre flottante qui ne vole jamais le focus ni les clics (le jeu garde la main)."""
    tk_win._dm_float = True
    if tk_win.winfo_ismapped():
        _nswindow(tk_win)
    else:
        tk_win.after_idle(lambda: tk_win.winfo_exists() and tk_win.winfo_ismapped() and _nswindow(tk_win))


def show_floating(tk_win):
    """Affiche sans activer l'appli (sinon le jeu perdrait le clavier)."""
    ns = getattr(tk_win, "_dm_ns", None)
    if ns is None:
        tk_win.deiconify()
        ns = _nswindow(tk_win)
    if ns is not None:
        ns.orderFrontRegardless()
    else:
        tk_win.lift()


def hide_floating(tk_win):
    ns = getattr(tk_win, "_dm_ns", None)
    if ns is not None:
        ns.orderOut_(None)
    else:
        tk_win.withdraw()
