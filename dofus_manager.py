# -*- coding: utf-8 -*-
"""Dofus Manager v4 — point d'entrée : fenêtre principale, navigation, tray, logique d'ordre."""
import json
import pathlib
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog

import dm_core as core
import dm_update
from dm_core import config, cycler, hotkeys, log

core.enable_dpi_awareness()  # avant toute création de fenêtre

import customtkinter as ctk  # noqa: E402
from PIL import ImageTk  # noqa: E402

from dm_pages import (HotkeysPage, PresetsPage, SettingsPage, StatsPage,  # noqa: E402
                      WindowsPage, button, confirm)
from dm_widgets import (ACCENT, ACCENT_SOFT, BG, BORDER, CARD, CARD_HOVER, SIDEBAR,  # noqa: E402
                        SUCCESS, TEXT, TEXT_DIM, TEXT_FAINT, WARNING, F, SwitchOverlay,
                        Toaster, icon, make_app_icon, resolve)

try:
    import pystray
    _HAS_TRAY = True
except Exception:
    _HAS_TRAY = False

ICO_PATH = core.APP_DIR / "icon.ico"

NAV = [("windows", "people", "Personnages", WindowsPage),
       ("presets", "star", "Presets", PresetsPage),
       ("stats", "stats", "Statistiques", StatsPage),
       ("hotkeys", "keyboard", "Raccourcis", HotkeysPage),
       ("settings", "settings", "Paramètres", SettingsPage)]


class App(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode(config.theme)
        super().__init__(fg_color=BG)
        self.withdraw()
        self.title(f"{core.APP_NAME} — {core.APP_AUTHOR}")
        self.geometry("1140x740")
        self.minsize(940, 620)

        self.icon_img = make_app_icon(256)
        self._splash = None if config.start_minimized else self._show_splash()
        self._splash_t = time.time()
        try:
            self.icon_img.save(ICO_PATH, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (256, 256)])
            self.iconbitmap(str(ICO_PATH))
            _patch_toplevel_icon()
        except Exception as e:
            log.debug("icon: %s", e)

        self.windows = []          # [{hwnd, pid, title, name, klass, order}]
        self.foreground = None
        self.cycle_active = False
        self.paused = False
        self.failed_hotkeys = []
        self.layout = {core.char_name(k): int(v) for k, v in core.load_layout().items()}
        self.presets = core.load_presets()
        self._pending_auto = config.auto_apply_last
        self._applied_preset = None   # preset dont l'ordre fait foi tant que l'utilisateur n'y touche pas
        self._tray = None
        self._tray_hint_shown = False
        self._update_busy = False
        self._pending_update = None
        self._quitting = False

        self.overlay = SwitchOverlay(self)
        self.toaster = Toaster(self)
        self._build()
        self.attributes("-topmost", config.always_on_top)

        hotkeys.start(config.hotkey_spec())
        core.turns.start()
        self.refresh()
        self.show_page("windows")
        if _HAS_TRAY:
            self._start_tray()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind_all("<Control-f>", lambda e: (self.show_page("windows"), self.pages["windows"].search.focus_set()))
        self.bind_all("<F5>", lambda e: self.refresh())
        for i, (key, *_rest) in enumerate(NAV, start=1):
            self.bind_all(f"<Control-Key-{i}>", lambda e, k=key: self.show_page(k))

        self.after(40, self._pump_events)
        self.after(400, self._tick_foreground)
        self.after(2500, self._tick_refresh)
        self.after(60000, self._tick_stats)
        if not (config.start_minimized and self._tray):
            remaining = max(0, int(1600 - (time.time() - self._splash_t) * 1000))
            self.after(remaining, self._end_splash)
        self.after(3000, self._periodic_update_check)  # après le splash, mainloop lancée
        _listen_show_requests()
        log.info("App started (v%s)", core.APP_VERSION)

    # ============================================================
    # MISE À JOUR
    # ============================================================
    # Les threads ne touchent jamais Tk (même self.after) : ils passent par core.events.
    _UPDATE_EVERY_MS = 6 * 3600 * 1000

    def _check_update(self, manual=False):
        found, error = None, None
        try:
            found = dm_update.check_update()
        except Exception as e:
            log.warning("Vérification MAJ : %s", e)
            error = str(e)
        core.events.put(("update_found", found, manual, error))

    def _start_update_check(self, manual=False):
        if self._update_busy:  # vérification, dialogue ou téléchargement déjà en cours
            if manual:
                self.toast("Mise à jour déjà en cours de traitement.")
            return
        self._update_busy = True
        threading.Thread(target=self._check_update, args=(manual,), daemon=True).start()

    def _periodic_update_check(self):
        # Session longue : on revérifie sans redémarrer l'appli.
        self._start_update_check()
        self.after(self._UPDATE_EVERY_MS, self._periodic_update_check)

    def check_update_now(self):
        if not self._update_busy:
            self.toast("Vérification en cours…")
        self._start_update_check(manual=True)

    def _on_update_found(self, found, manual, error=None):
        if found and (manual or found[0] != config.dismissed_update_tag):
            if not self.winfo_viewable():
                # Fenêtre cachée dans le tray : un dialogue modal y serait invisible.
                self._pending_update = (found, manual)
                self._update_busy = False
                if self._tray:
                    try:
                        self._tray.notify(f"Version {found[0]} disponible — ouvrez Dofus Manager "
                                          "pour l'installer.", core.APP_NAME)
                    except Exception:
                        pass
                return
            self._offer_update(*found, manual=manual)
            return
        self._update_busy = False
        if manual:
            if error:
                self.toast("Vérification impossible : GitHub injoignable (connexion internet ?).", "warning")
            else:
                self.toast("Vous avez déjà la dernière version.")

    def _offer_update(self, tag, notes, asset_name, manual=False):
        self._pending_update = None
        msg = f"La version {tag} de {core.APP_NAME} est disponible (vous avez la {core.APP_VERSION})."
        if notes:
            msg += "\n\n" + (notes if len(notes) < 400 else notes[:397] + "…")
        if not confirm(self, "Mise à jour disponible", msg, "Mettre à jour maintenant"):
            self._update_busy = False
            if not manual and config.dismissed_update_tag != tag:
                config.dismissed_update_tag = tag
                config.save()
            return
        if config.dismissed_update_tag:
            config.dismissed_update_tag = ""
            config.save()
        self.toast(f"Téléchargement de {tag}…", "info")

        def work():
            try:
                core.events.put(("update_ready", dm_update.download(tag, asset_name)))
            except Exception as e:
                core.events.put(("update_error", str(e)))
        threading.Thread(target=work, daemon=True).start()

    def _install_update(self, path):
        try:
            dm_update.install_and_restart(path)
        except Exception as e:
            log.error("Installation MAJ : %s", e)
            self._update_busy = False
            self.toast(f"Mise à jour impossible : {e}", "error")
            return
        self.quit_app()

    # ============================================================
    # ÉCRAN DE DÉMARRAGE
    # ============================================================
    def _show_splash(self):
        s = tk.Toplevel(self)
        s.overrideredirect(True)
        s.attributes("-topmost", True)
        bg = resolve(CARD)
        s.configure(bg=ACCENT)
        body = tk.Frame(s, bg=bg)
        body.pack(padx=1, pady=1)
        self._splash_img = ImageTk.PhotoImage(self.icon_img.resize((84, 84)))
        tk.Label(body, image=self._splash_img, bg=bg).pack(padx=100, pady=(34, 12))
        tk.Label(body, text=core.APP_NAME, bg=bg, fg=resolve(TEXT), font=F(20, "bold")).pack()
        tk.Label(body, text=f"Version {core.APP_VERSION}", bg=bg, fg=resolve(TEXT_FAINT), font=F(10)).pack()
        tk.Label(body, text=f"Créé par {core.APP_AUTHOR}", bg=bg, fg=ACCENT,
                 font=F(12, "bold")).pack(pady=(18, 2))
        tk.Label(body, text=f"{core.COPYRIGHT} — Tous droits réservés", bg=bg, fg=resolve(TEXT_DIM),
                 font=F(9)).pack(pady=(0, 28))
        s.update_idletasks()
        w, h = s.winfo_reqwidth(), s.winfo_reqheight()
        s.geometry(f"+{(s.winfo_screenwidth() - w) // 2}+{(s.winfo_screenheight() - h) // 2}")
        s.update()
        return s

    def _end_splash(self):
        if self._splash:
            self._splash.destroy()
            self._splash = None
        self.deiconify()
        self.lift()

    def _tick_stats(self):
        try:
            core.stats.flush()
        finally:
            self.after(60000, self._tick_stats)

    # ============================================================
    # UI
    # ============================================================
    def _build(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        side = ctk.CTkFrame(self, width=236, corner_radius=0, fg_color=SIDEBAR)
        side.grid(row=0, column=0, sticky="nsw")
        side.pack_propagate(False)
        ctk.CTkFrame(self, width=1, corner_radius=0, fg_color=BORDER).grid(row=0, column=0, sticky="nse")

        brand = ctk.CTkFrame(side, fg_color="transparent")
        brand.pack(fill="x", padx=20, pady=(24, 26))
        logo = ctk.CTkImage(self.icon_img, size=(36, 36))
        ctk.CTkLabel(brand, image=logo, text="").pack(side="left")
        txt = ctk.CTkFrame(brand, fg_color="transparent")
        txt.pack(side="left", padx=12)
        ctk.CTkLabel(txt, text="Dofus Manager", font=F(16, "bold"), text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(txt, text=f"Version {core.APP_VERSION}", font=F(11), text_color=TEXT_FAINT).pack(anchor="w")

        self.nav_buttons, self.nav_icons = {}, {}
        for key, ico, label, _ in NAV:
            self.nav_icons[key] = (icon(ico, 18, TEXT_DIM), icon(ico, 18, ACCENT))
            b = ctk.CTkButton(side, text="  " + label, image=self.nav_icons[key][0], compound="left",
                              anchor="w", height=42, corner_radius=10, font=F(13, "bold"),
                              fg_color="transparent", hover_color=CARD_HOVER, text_color=TEXT_DIM,
                              command=lambda k=key: self.show_page(k))
            b.pack(fill="x", padx=14, pady=2)
            self.nav_buttons[key] = b

        ctk.CTkLabel(side, text=f"{core.COPYRIGHT}", font=F(10), text_color=TEXT_FAINT).pack(side="bottom",
                                                                                           pady=(0, 12))
        status = ctk.CTkFrame(side, fg_color=CARD, corner_radius=14, border_width=1, border_color=BORDER)
        status.pack(side="bottom", fill="x", padx=14, pady=(16, 8))
        row = ctk.CTkFrame(status, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(14, 2))
        self.st_dot = ctk.CTkLabel(row, text="●", font=F(12), text_color=TEXT_FAINT)
        self.st_dot.pack(side="left")
        self.st_title = ctk.CTkLabel(row, text="", font=F(12, "bold"), text_color=TEXT)
        self.st_title.pack(side="left", padx=6)
        self.st_detail = ctk.CTkLabel(status, text="", font=F(11), text_color=TEXT_DIM, anchor="w",
                                      justify="left", wraplength=180)
        self.st_detail.pack(fill="x", padx=14)
        self.st_keys = ctk.CTkLabel(status, text="", font=F(11, "bold"), text_color=ACCENT,
                                    fg_color=ACCENT_SOFT, corner_radius=7, height=26)
        self.st_keys.pack(fill="x", padx=14, pady=(8, 8))
        self.pause_btn = button(status, "⏸  Pause", lambda: self.set_paused(not self.paused), "ghost")
        self.pause_btn.pack(fill="x", padx=14, pady=(0, 14))

        content = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        content.grid(row=0, column=1, sticky="nsew")
        self.pages = {key: cls(content, self) for key, _, _, cls in NAV}
        self.current = None
        self._update_status()

    def show_page(self, key):
        if self.current == key:
            return
        if self.current:
            self.pages[self.current].pack_forget()
            self.nav_buttons[self.current].configure(fg_color="transparent", text_color=TEXT_DIM,
                                                     image=self.nav_icons[self.current][0])
        self.current = key
        self.nav_buttons[key].configure(fg_color=ACCENT_SOFT, text_color=ACCENT,
                                        image=self.nav_icons[key][1])
        self.pages[key].pack(fill="both", expand=True)
        self.pages[key].on_show()

    def _update_status(self):
        n = len(cycler.snapshot())
        if self.paused:
            dot, title, detail = WARNING, "En pause", "Les raccourcis sont libérés."
        elif self.cycle_active and n:
            dot, title = SUCCESS, "Cyclage actif"
            detail = f"{n} personnage{'s' if n > 1 else ''} dans le cycle"
            cur = next((w for w in self.windows if w["hwnd"] == self.foreground and w["order"]), None)
            if cur:
                detail = f"{cur['order']}/{n}  ·  {cur['name']}"
        else:
            dot, title, detail = TEXT_FAINT, "Cyclage inactif", "Placez vos personnages puis activez."
        self.st_dot.configure(text_color=dot)
        self.st_title.configure(text=title)
        self.st_detail.configure(text=detail)
        self.st_keys.configure(text=f"{core.combo_name(config.vkey_prev, config.mods_prev)}  ◀    ▶  "
                                    f"{core.combo_name(config.vkey_next, config.mods_next)}")
        self.pause_btn.configure(text="Reprendre" if self.paused else "Pause",
                                 image=icon("play" if self.paused else "pause", 14, TEXT), compound="left")

    def toast(self, text, kind="info"):
        self.toaster.show(text, kind)

    # ============================================================
    # BOUCLES
    # ============================================================
    def _pump_events(self):
        if self._quitting:
            return
        for _ in range(200):  # borne : l'UI reste réactive même sous une rafale d'événements
            try:
                ev = core.events.get_nowait()
            except queue.Empty:
                break
            try:  # un événement en erreur ne doit pas bloquer les suivants
                self._handle_event(ev)
            except tk.TclError as e:
                # Race bénigne de CustomTkinter : géométrie mise à jour sur une page pas encore affichée.
                log.debug("Event %s (UI non affichée) : %s", ev[0], e)
            except Exception:
                log.exception("Event %s", ev[0])
        self.after(40, self._pump_events)

    def _handle_event(self, ev):
        kind = ev[0]
        if kind == "switch":
            _, order, hwnd, title = ev
            if config.show_overlay:
                self.overlay.show(order, hwnd, title, total=len(cycler.snapshot()))
            self._set_foreground(hwnd)
        elif kind == "hotkeys":
            self._on_hotkey_status(ev[1])
        elif kind == "tray":
            self._on_tray(ev[1], ev[2] if len(ev) > 2 else None)
        elif kind == "preset_hotkey" and ev[1] in self.presets:
            self.apply_preset(ev[1])
            if self._ordered():
                self.focus_char(self._ordered()[0]["hwnd"])
        elif kind == "notice":
            self.toast(ev[1], "warning")
        elif kind == "update_found":
            self._on_update_found(*ev[1:])
        elif kind == "update_ready":
            self._install_update(ev[1])
        elif kind == "update_error":
            self._update_busy = False
            self.toast(f"Mise à jour impossible : {ev[1]}", "error")

    def _tick_foreground(self):
        try:
            self._set_foreground(core.user32.GetForegroundWindow())
        finally:
            self.after(400, self._tick_foreground)

    def _set_foreground(self, hwnd):
        if hwnd == self.foreground:
            return
        self.foreground = hwnd
        self.pages["windows"].highlight(hwnd)
        self._update_status()

    def _tick_refresh(self):
        try:
            wins = core.enum_dofus_windows()
            if {w["hwnd"] for w in wins} != {w["hwnd"] for w in self.windows} or \
               any(w["title"] != o["title"] for w in wins for o in self.windows if o["hwnd"] == w["hwnd"]):
                self.refresh(wins)
        except Exception as e:
            log.error("Auto-refresh: %s", e)
        finally:
            self.after(2500, self._tick_refresh)

    # ============================================================
    # FENÊTRES & ORDRE
    # ============================================================
    def refresh(self, wins=None):
        wins = core.enum_dofus_windows() if wins is None else wins
        new_cls = {w["name"]: w["klass"] for w in wins
                   if w["klass"] and config.char_classes.get(w["name"]) != w["klass"]}
        if new_cls:
            config.char_classes.update(new_cls)
            config.save()
        known = {w["hwnd"]: w["order"] for w in self.windows}
        for w in wins:
            w["order"] = known[w["hwnd"]] if w["hwnd"] in known else int(self.layout.get(w["name"], 0))
        self.windows = sorted(wins, key=lambda w: (w["order"] <= 0, w["order"], w["name"].lower()))
        self._follow_preset({w["name"].lower() for w in wins if w["hwnd"] not in known})
        self._renumber(self._ordered())
        if self._pending_auto and self.windows:
            self._auto_apply()
        if self.cycle_active:
            self._push_cycle()
        self._rerender()

    def _follow_preset(self, new_names):
        """Perso d'un preset appliqué qui se connecte après coup : il prend sa place dans le preset
        (sinon il reprenait sa position mémorisée, en conflit avec l'ordre du preset)."""
        preset = self.presets.get(self._applied_preset) if self._applied_preset else None
        if not preset or not new_names or self._pending_auto:
            return
        members = {n.lower() for n in preset}
        others = {w["name"].lower() for w in self.windows
                  if w["order"] > 0 and w["name"].lower() not in new_names}
        if new_names & members and others <= members:  # l'ordre n'a pas été retouché à la main
            self._assign_names(preset)
            self._save_layout()

    def _auto_apply(self):
        name = config.active_preset
        if name in self.presets:
            self._assign_names(self.presets[name])
            self._applied_preset = name
        if self._ordered():
            self._pending_auto = False
            self.cycle_active = True
            self._push_cycle()
            self._save_layout()
            log.info("Cyclage repris automatiquement (%d persos)", len(self._ordered()))

    def _get(self, hwnd):
        return next((w for w in self.windows if w["hwnd"] == hwnd), None)

    def _ordered(self):
        return sorted([w for w in self.windows if w["order"] > 0], key=lambda w: (w["order"], w["name"].lower()))

    @staticmethod
    def _renumber(ordered):
        for i, w in enumerate(ordered, start=1):
            w["order"] = i

    def _push_cycle(self):
        cycler.set_order([(w["order"], w["hwnd"], w["title"]) for w in self.windows])
        if not cycler.snapshot():
            self.cycle_active = False

    def _save_layout(self):
        present = {w["name"] for w in self.windows}
        # On garde la position mémorisée des persos absents (déconnectés temporairement).
        self.layout = {n: o for n, o in self.layout.items() if n not in present}
        self.layout.update({w["name"]: w["order"] for w in self.windows if w["order"] > 0})
        core.save_layout(self.layout)

    def _order_changed(self):
        self.windows.sort(key=lambda w: (w["order"] <= 0, w["order"], w["name"].lower()))
        self._save_layout()
        if self.cycle_active:
            self._push_cycle()
        self._rerender()

    def _rerender(self):
        self.pages["windows"].render()
        if self.current == "presets":
            self.pages["presets"].render()
        self._update_status()

    def move_to(self, hwnd, pos):
        w = self._get(hwnd)
        if not w:
            return
        self._applied_preset = None  # ordre personnalisé : il prime sur le preset
        ordered = [x for x in self._ordered() if x is not w]
        if pos <= 0:
            w["order"] = 0
        else:
            ordered.insert(min(pos - 1, len(ordered)), w)
        self._renumber(ordered)
        self._order_changed()

    def move(self, hwnd, delta):
        w = self._get(hwnd)
        if w and w["order"] > 0:
            self.move_to(hwnd, max(1, w["order"] + delta))

    def add_to_cycle(self, hwnd):
        self.move_to(hwnd, len(self._ordered()) + 1)

    def focus_char(self, hwnd):  # ne pas nommer « focus » : masquerait tkinter.Misc.focus
        w = self._get(hwnd)
        if w and core.focus_window(hwnd, config.auto_maximize) and config.show_overlay:
            self.overlay.show(w["order"], hwnd, w["title"], total=len(self._ordered()))

    def apply_order(self):
        if not self._ordered():
            self.toast("Ajoutez au moins un personnage au cycle.", "warning")
            return
        self.cycle_active = True
        self._pending_auto = False
        self._push_cycle()
        self._rerender()
        self.toast(f"Cyclage actif · {len(self._ordered())} personnages  —  "
                   f"{core.combo_name(config.vkey_next, config.mods_next)} suivant, "
                   f"{core.combo_name(config.vkey_prev, config.mods_prev)} précédent", "success")

    def reset_order(self):
        if not self._ordered():
            return
        if not confirm(self, "Tout retirer du cycle", "Les positions de tous les personnages seront effacées.",
                       "Tout retirer", danger=True):
            return
        for w in self.windows:
            w["order"] = 0
        self._applied_preset = None
        self.layout = {}
        core.save_layout(self.layout)
        self.cycle_active = False
        cycler.set_order([])
        self._rerender()
        self.toast("Cycle vidé.")

    # ============================================================
    # PRESETS
    # ============================================================
    def _assign_names(self, names):
        by_name = {w["name"].lower(): w for w in self.windows}
        for w in self.windows:
            w["order"] = 0
        found = [by_name[n.lower()] for n in names if n.lower() in by_name]
        self._renumber(found)
        return len(found)

    def apply_preset(self, name):
        if name not in self.presets:
            return
        names = self.presets[name]
        k = self._assign_names(names)
        self._applied_preset = name if k else None
        self.cycle_active = k > 0
        self._pending_auto = False
        if k:
            self._push_cycle()
        self._order_changed()
        self.toast(f"« {name} » appliqué  ·  {k}/{len(names)} connecté{'s' if k > 1 else ''}",
                   "success" if k == len(names) else ("warning" if k else "error"))
        self._tray_refresh()

    def save_preset(self, orig, name, names):
        if orig and orig != name:
            self.presets.pop(orig, None)
            if self._applied_preset == orig:
                self._applied_preset = name
            if config.active_preset == orig:
                config.active_preset = name
            if orig in config.preset_keys:
                config.preset_keys[name] = config.preset_keys.pop(orig)
            self._hotkeys_changed()
        self.presets[name] = names
        core.save_presets(self.presets)
        self.pages["presets"].render()
        self.pages["windows"].refresh_presets()
        self._tray_refresh()
        self.toast(f"Preset « {name} » enregistré.")

    def delete_preset(self, name):
        self.presets.pop(name, None)
        if self._applied_preset == name:
            self._applied_preset = None
        core.save_presets(self.presets)
        if config.active_preset == name:
            config.active_preset = ""
        config.preset_keys.pop(name, None)
        self._hotkeys_changed()
        self.pages["presets"].render()
        self.pages["windows"].refresh_presets()
        self._tray_refresh()

    def set_default_preset(self, name):
        config.active_preset = name
        config.save()
        self.pages["presets"].render()
        if name:
            self.toast(f"« {name} » sera appliqué automatiquement au démarrage.")

    # ============================================================
    # RACCOURCIS
    # ============================================================
    # Emplacements : "next", "prev", ("direct", i), ("preset", nom)
    def slot_label(self, slot):
        if slot == "next":
            return "Personnage suivant"
        if slot == "prev":
            return "Personnage précédent"
        kind, arg = slot
        if kind == "preset":
            return f"Preset « {arg} »"
        if arg < len(config.direct_keys):
            return core.target_label(config.direct_keys[arg]["target"])
        return f"Position {arg + 1}"

    def _slot_combos(self):
        combos = {"next": (config.vkey_next, config.mods_next), "prev": (config.vkey_prev, config.mods_prev)}
        combos.update({("direct", i): (d["vkey"], d["mods"]) for i, d in enumerate(config.direct_keys)})
        combos.update({("preset", n): (v["vkey"], v["mods"]) for n, v in config.preset_keys.items()})
        return combos

    def set_hotkey(self, slot, combo):
        if combo is None:
            if isinstance(slot, tuple) and slot[0] == "direct":
                self.remove_direct_key(slot[1])
            elif isinstance(slot, tuple) and config.preset_keys.pop(slot[1], None):
                self._hotkeys_changed()
            return
        for other, c in self._slot_combos().items():
            if other != slot and tuple(c) == tuple(combo):
                self.toast(f"{core.combo_name(*combo)} est déjà utilisé : {self.slot_label(other)}.", "warning")
                return
        vk, mods = combo
        if slot == "next":
            config.vkey_next, config.mods_next = vk, mods
        elif slot == "prev":
            config.vkey_prev, config.mods_prev = vk, mods
        elif slot[0] == "preset":
            config.preset_keys[slot[1]] = {"vkey": vk, "mods": mods}
        elif slot[1] < len(config.direct_keys):
            config.direct_keys[slot[1]].update(vkey=vk, mods=mods)
        else:
            config.direct_keys.append({"vkey": vk, "mods": mods,
                                       "target": f"pos:{len(config.direct_keys) + 1}"})
        self._hotkeys_changed()

    def set_direct_target(self, i, target):
        if 0 <= i < len(config.direct_keys):
            config.direct_keys[i]["target"] = target
            self._hotkeys_changed()

    def class_of(self, name):
        w = next((w for w in self.windows if w["name"].lower() == name.lower()), None)
        if w:
            return w["klass"]
        return next((k for n, k in config.char_classes.items() if n.lower() == name.lower()), "")

    def known_chars(self):
        names = {w["name"] for w in self.windows} | set(self.layout)
        for chars in self.presets.values():
            names.update(chars)
        return sorted(names, key=str.lower)

    # ============================================================
    # DISPOSITION
    # ============================================================
    def layout_choices(self):
        mons = core.list_monitors()
        out = []
        for i, m in enumerate(mons):
            name = f"écran {i + 1}{' (principal)' if m['primary'] else ''}"
            out.append((f"Plein écran · {name}", "single", i))
            out.append((f"Mosaïque · {name}", "grid", i))
        if len(mons) > 1:
            out.append(("Un perso par écran", "spread", 0))
        out.append(("Tout maximiser", "maximize", 0))
        return out

    def arrange(self, mode, monitor=0):
        targets = self._ordered() or self.windows
        n = core.arrange_windows([w["hwnd"] for w in targets], mode, monitor)
        if not n:
            self.toast("Aucune fenêtre à disposer.", "warning")
            return
        msg = f"{n} fenêtre{'s' if n > 1 else ''} disposée{'s' if n > 1 else ''}."
        if mode == "grid" and config.auto_maximize:
            config.auto_maximize = False
            config.save()
            msg += " « Maximiser au focus » désactivé pour garder la mosaïque."
        elif mode != "grid" and not config.auto_maximize:
            config.auto_maximize = True
            config.save()
            msg += " « Maximiser au focus » réactivé."
        self.after(150, lambda: (self.lift(), self.focus_force()))
        self.toast(msg, "success")

    def remove_direct_key(self, i):
        if 0 <= i < len(config.direct_keys):
            config.direct_keys.pop(i)
            self._hotkeys_changed()

    def _hotkeys_changed(self):
        config.save()
        hotkeys.apply(config.hotkey_spec())
        self.pages["hotkeys"].render()
        self._update_status()

    def _on_hotkey_status(self, failed):
        self.failed_hotkeys = failed
        self.pages["hotkeys"].set_failed(failed)
        self.pages["windows"].set_banner(
            ("Raccourcis indisponibles : " + ", ".join(failed) + " — changez-les dans Raccourcis.") if failed else "")
        if failed:
            self.toast("Certains raccourcis sont déjà pris par une autre application.", "error")

    def set_paused(self, paused):
        self.paused = bool(paused)
        hotkeys.set_paused(self.paused)
        self._update_status()
        var = getattr(self.pages["hotkeys"], "pause_var", None)
        if var is not None and var.get() != self.paused:
            var.set(self.paused)
        self._tray_refresh()
        self.toast("Raccourcis en pause." if self.paused else "Raccourcis réactivés.")

    # ============================================================
    # PARAMÈTRES
    # ============================================================
    def set_theme(self, mode):
        config.theme = mode
        config.save()
        ctk.set_appearance_mode(mode)

    def set_option(self, key, value, save=True):
        setattr(config, key, value)
        if save:
            config.save()
        if key == "always_on_top":
            self.attributes("-topmost", bool(value))

    def set_startup(self, enabled):
        core.set_startup_enabled(enabled)
        self.toast("Lancement au démarrage de Windows " + ("activé." if enabled else "désactivé."))

    def test_overlay(self):
        w = self._get(self.foreground) or (self._ordered() or self.windows or [None])[0]
        if w:
            self.overlay.show(w["order"] or 1, w["hwnd"], w["title"], total=len(self._ordered()))
        else:
            self.overlay.show(1, None, "Exoticlozie - Sadida", total=4)

    def export_layout(self):
        fp = filedialog.asksaveasfilename(parent=self, defaultextension=".json", title="Exporter l'ordre",
                                          initialfile="dofus_ordre.json",
                                          filetypes=[("JSON", "*.json"), ("Tous", "*.*")])
        if not fp:
            return
        data = {w["name"]: w["order"] for w in self._ordered()}
        try:
            pathlib.Path(fp).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self.toast(f"Ordre exporté vers {pathlib.Path(fp).name}.")
        except Exception as e:
            self.toast(f"Export impossible : {e}", "error")

    def import_layout(self):
        fp = filedialog.askopenfilename(parent=self, title="Importer un ordre",
                                        filetypes=[("JSON", "*.json"), ("Tous", "*.*")])
        if not fp:
            return
        try:
            raw = json.loads(pathlib.Path(fp).read_text(encoding="utf-8"))
            data = {core.char_name(k).lower(): int(v) for k, v in raw.items()}  # accepte l'ancien format (titres)
        except Exception as e:
            self.toast(f"Fichier invalide : {e}", "error")
            return
        n = 0
        self._applied_preset = None
        for w in self.windows:
            w["order"] = data.get(w["name"].lower(), 0)
            n += w["order"] > 0
        self._renumber(self._ordered())
        self._order_changed()
        self.toast(f"{n} position{'s' if n > 1 else ''} importée{'s' if n > 1 else ''}.")

    # ============================================================
    # TRAY
    # ============================================================
    def _start_tray(self):
        post = lambda *ev: (lambda icon=None, item=None: core.events.put(("tray",) + ev))  # noqa: E731

        def preset_items():
            return [pystray.MenuItem(n, post("preset", n)) for n in list(self.presets)] or \
                   [pystray.MenuItem("Aucun preset", None, enabled=False)]

        menu = pystray.Menu(
            pystray.MenuItem("Ouvrir", post("open"), default=True),
            pystray.MenuItem("Pause des raccourcis", post("pause"), checked=lambda item: self.paused),
            pystray.MenuItem("Appliquer un preset", pystray.Menu(preset_items)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quitter", post("quit")),
        )
        try:
            self._tray = pystray.Icon("DofusManager", make_app_icon(64),
                                      f"{core.APP_NAME} · {core.APP_AUTHOR}", menu)
            threading.Thread(target=self._tray.run, daemon=True).start()
        except Exception as e:
            log.warning("Tray indisponible : %s", e)
            self._tray = None

    def _tray_refresh(self):
        if self._tray:
            try:
                self._tray.update_menu()
            except Exception:
                pass

    def _on_tray(self, action, arg=None):
        if action == "open":
            if self._splash:  # 2e lancement pendant l'écran de démarrage
                return
            self.deiconify()
            self.lift()
            self.focus_force()
            if self._pending_update and not self._update_busy:
                found, manual = self._pending_update
                self._update_busy = True
                self.after(300, lambda: self._offer_update(*found, manual=manual))
        elif action == "pause":
            self.set_paused(not self.paused)
        elif action == "preset" and arg in self.presets:  # menu tray pas encore rafraîchi
            self.apply_preset(arg)
        elif action == "quit":
            self.quit_app()

    def _on_close(self):
        if config.minimize_to_tray and self._tray:
            self.withdraw()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                try:
                    self._tray.notify("Dofus Manager reste actif dans la zone de notification.", core.APP_NAME)
                except Exception:
                    pass
        else:
            self.quit_app()

    def quit_app(self):
        if self._quitting:
            return
        self._quitting = True
        core.stats.flush()
        hotkeys.stop()
        core.turns.stop()
        if self._tray:
            try:
                self._tray.stop()
            except Exception:
                pass
        log.info("App stopped")
        self.destroy()


def _patch_toplevel_icon():
    """CustomTkinter impose son icône aux fenêtres secondaires : on remet la nôtre."""
    orig = ctk.CTkToplevel.__init__

    def init(self, *a, **k):
        orig(self, *a, **k)
        self.after(260, lambda: self.winfo_exists() and self.iconbitmap(str(ICO_PATH)))

    ctk.CTkToplevel.__init__ = init


_SHOW_EVENT = "Local\\DofusManager_ShowWindow"


def _listen_show_requests():
    """Un 2e lancement (raccourci, menu Démarrer) réaffiche l'instance déjà ouverte."""
    try:
        import win32event
        h = win32event.CreateEvent(None, False, False, _SHOW_EVENT)
    except Exception as e:
        log.debug("Événement d'affichage : %s", e)
        return

    def wait():
        while True:
            if win32event.WaitForSingleObject(h, win32event.INFINITE) == win32event.WAIT_OBJECT_0:
                core.events.put(("tray", "open"))
    threading.Thread(target=wait, daemon=True).start()


def _signal_running_instance():
    try:
        import win32event
        h = win32event.OpenEvent(0x0002, False, _SHOW_EVENT)  # EVENT_MODIFY_STATE
        win32event.SetEvent(h)
        return True
    except Exception:
        return False  # instance plus ancienne sans cet événement


def main():
    if not core.acquire_single_instance():
        log.warning("Instance déjà lancée — arrêt.")
        if _signal_running_instance():
            sys.exit(0)
        ctk.set_appearance_mode(config.theme)
        root = ctk.CTk()
        root.withdraw()
        from tkinter import messagebox
        messagebox.showinfo(core.APP_NAME, "Dofus Manager est déjà lancé.\n"
                                           "Retrouvez-le dans la zone de notification.")
        root.destroy()
        sys.exit(0)
    App().mainloop()


if __name__ == "__main__":
    main()
