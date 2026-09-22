# -*- coding: utf-8 -*-
"""Dofus Manager — logique (détection, focus, cyclage, raccourcis, persistance).

Aucune interaction avec la mémoire du jeu : uniquement des API de fenêtrage du système
(Win32 sous Windows, Accessibility/Quartz sous macOS — voir dm_win.py et dm_mac.py).
"""
import copy
from datetime import date
import json
import logging
import logging.handlers
import os
import pathlib
import queue
import re
import sys
import threading
import time

IS_MAC = sys.platform == "darwin"

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
# COUCHE SYSTÈME (fenêtres, raccourcis globaux, souris, écrans, démarrage)
# ============================================================
# Le module de plateforme importe dm_core en retour : il ne lit ses attributs qu'à l'appel.
if IS_MAC:
    from dm_mac import *  # noqa: E402,F401,F403
else:
    from dm_win import *  # noqa: E402,F401,F403


def combo_name(vk, mods=0):
    if not vk:
        return "—"
    m = mods_name(mods)
    return f"{m}+{vk_name(vk)}" if m else vk_name(vk)



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
        "vkey_next": DEFAULT_NEXT, "mods_next": 0,
        "vkey_prev": DEFAULT_PREV, "mods_prev": 0,
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
        alive = [x for x in self.order if is_window(x[1])]
        if len(alive) != len(self.order):
            self.order, self._idx = alive, -1

    def _sync(self):
        fg = get_foreground_window()
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
        title = window_title(target[1]).strip() or target[2]  # titre à jour pour l'overlay
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



hotkeys = HotkeyManager()
turns = TurnWatcher()
