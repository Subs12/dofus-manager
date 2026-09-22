# -*- coding: utf-8 -*-
"""Dofus Manager — couche Windows (API de fenêtrage Win32).

Aucune interaction avec la mémoire du jeu : uniquement des API de fenêtrage Win32.
"""
import ctypes
from ctypes import wintypes
import math
import os
import pathlib
import queue
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

import dm_core as core

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
        core.log.error("Démarrage Windows : %s", e)

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
                name, klass = core.split_title(title)
                out.append({"hwnd": hwnd, "pid": pid, "title": title,
                            "name": name, "klass": klass})
        except Exception:
            pass

    win32gui.EnumWindows(cb, None)
    return out


def focus_window(hwnd, maximize=True):
    if not win32gui.IsWindow(hwnd):
        core.log.warning("Focus ignoré : fenêtre fermée (hwnd=%s)", hwnd)
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

        core.stats.on_focus(core.char_name(win32gui.GetWindowText(hwnd)))
        return True
    except Exception as e:
        core.log.error("Focus error: %s", e)
        return False
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
        core.log.error("Écrans : %s", e)
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
        core.log.error("Disposition : %s", e)
    core.log.info("Disposition %s : %d fenêtres", mode, len(hwnds))
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
            core.log.warning("Crochet souris non installé : boutons de souris indisponibles.")
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
                core.log.error("Crochet souris : %s", e)
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
            entries.append((_HK_DIRECT + i, (vk, mods), core.target_label(target)))
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
                mouse_labels.append(f"{label} ({core.combo_name(vk, mods)})")
            elif user32.RegisterHotKey(None, hk_id, MOD_NOREPEAT | int(mods), int(vk)):
                ids.append(hk_id)
            else:
                failed.append(f"{label} ({core.combo_name(vk, mods)})")
        if self._mouse_binds and not self._mouse.install():
            self._mouse_binds = {}
            failed.extend(mouse_labels)
        elif not self._mouse_binds:
            self._mouse.remove()
        if failed:
            core.log.warning("Raccourcis non enregistrés (déjà pris par une autre appli ?) : %s", failed)
        core.events.put(("hotkeys", failed))
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
        return not core.config.mouse_passthrough

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
                    core.run_action(self._actions.get(msg.wParam))
                except Exception as e:
                    core.log.error("Hotkey dispatch error: %s", e)
        self._unregister(ids)



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
                core.log.warning("Suivi des tours indisponible.")
                return
            win32gui.PumpMessages()
        except Exception as e:
            core.log.error("Suivi des tours : %s", e)
        finally:
            self._hwnd = None

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if self._shell_msg and msg == self._shell_msg:
            if wparam == _HSHELL_FLASH and core.config.turn_focus:
                try:
                    self._on_flash(lparam)
                except Exception as e:
                    core.log.error("Suivi des tours : %s", e)
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
        if core.hotkeys.paused or not win32gui.IsWindow(hwnd):
            return
        fg = user32.GetForegroundWindow()
        # Déjà affiché, ou l'utilisateur est hors du jeu (chat, navigateur) : on ne vole pas le focus.
        if hwnd == fg or not _is_game_window(fg):
            return
        order = next((o for o, h, _ in core.cycler.snapshot() if h == hwnd), 0)
        if not order and (core.config.turn_focus_cycle_only or not _is_game_window(hwnd)):
            return
        now = time.time()
        if now - self._last.get(hwnd, 0) < 1.5:  # une fenêtre clignote plusieurs fois par tour
            return
        self._last[hwnd] = now
        if focus_window(hwnd, core.config.auto_maximize):
            title = win32gui.GetWindowText(hwnd).strip()
            core.events.put(("switch", order, hwnd, title))
            core.log.info("Début de tour : %s", core.char_name(title))



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
        core.log.warning("Mutex d'instance : %s", e)
        return False
    return win32api.GetLastError() != winerror.ERROR_ALREADY_EXISTS


# ============================================================
# INTERFACE COMMUNE AVEC dm_mac (utilisée par dm_core et l'interface)
# ============================================================
DEFAULT_NEXT, DEFAULT_PREV = VK_F23, VK_F21
STARTUP_LABEL = "Démarrer avec Windows"
TRAY_LABEL = "zone de notification"
SHORTCUT_MOD = "Control"      # modificateur des raccourcis de l'interface (Ctrl+F…)
SHORTCUT_MOD_NAME = "Ctrl"
HAS_TURN_WATCH = True


def is_window(hwnd):
    return bool(win32gui.IsWindow(hwnd))


def get_foreground_window():
    return user32.GetForegroundWindow()


def window_title(hwnd):
    return win32gui.GetWindowText(hwnd)


def open_folder(path):
    os.startfile(path)


def make_click_through(tk_win):
    """Fenêtre flottante qui ne vole jamais le focus ni les clics (le jeu garde la main)."""
    try:
        tk_win.update_idletasks()
        hwnd = win32gui.GetParent(tk_win.winfo_id()) or tk_win.winfo_id()
        ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        ex |= (win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT |
               win32con.WS_EX_TOOLWINDOW | 0x08000000)  # WS_EX_NOACTIVATE
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex)
    except Exception as e:
        core.log.debug("click-through: %s", e)


def show_floating(tk_win):
    tk_win.deiconify()
    tk_win.lift()


def hide_floating(tk_win):
    tk_win.withdraw()


_SHOW_EVENT = "Local\\DofusManager_ShowWindow"


def listen_show_requests(on_request):
    """Un 2e lancement (raccourci, menu Démarrer) réaffiche l'instance déjà ouverte."""
    try:
        h = win32event.CreateEvent(None, False, False, _SHOW_EVENT)
    except Exception as e:
        core.log.debug("Événement d'affichage : %s", e)
        return

    def wait():
        while True:
            if win32event.WaitForSingleObject(h, win32event.INFINITE) == win32event.WAIT_OBJECT_0:
                on_request()
    threading.Thread(target=wait, daemon=True).start()


def signal_running_instance():
    try:
        h = win32event.OpenEvent(0x0002, False, _SHOW_EVENT)  # EVENT_MODIFY_STATE
        win32event.SetEvent(h)
        return True
    except Exception:
        return False  # instance plus ancienne sans cet événement
