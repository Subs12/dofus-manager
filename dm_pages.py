# -*- coding: utf-8 -*-
"""Dofus Manager — pages de l'interface (Personnages, Presets, Stats, Raccourcis, Paramètres)."""
import csv
import os
import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk

import dm_core as core
from dm_core import config
from dm_widgets import (ACCENT, ACCENT_HOVER, ACCENT_SOFT, BG, BORDER, CARD, CARD_ACTIVE,
                        CARD_HOVER, DANGER, DANGER_SOFT, SUCCESS, TEXT, TEXT_DIM, TEXT_FAINT,
                        WARNING, F, KeyCaptureDialog, class_avatar, class_color, icon, order_color,
                        resolve)

# ============================================================
# HELPERS UI
# ============================================================
_BTN = {
    "primary": dict(fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="white", border_width=0),
    "ghost":   dict(fg_color=CARD, hover_color=CARD_HOVER, text_color=TEXT,
                    border_width=1, border_color=BORDER),
    "danger":  dict(fg_color=DANGER_SOFT, hover_color=("#FAD7D7", "#3A1B1E"),
                    text_color=DANGER, border_width=0),
    "subtle":  dict(fg_color="transparent", hover_color=CARD_HOVER, text_color=TEXT_DIM,
                    border_width=0),
}


_ICON_COLOR = {"primary": "white", "ghost": TEXT, "danger": DANGER, "subtle": TEXT_DIM}


def button(master, text, command, kind="ghost", width=40, height=34, ico=None, **kw):
    if ico:
        kw.update(image=icon(ico, 15, _ICON_COLOR[kind]), compound="left")
        text = ("  " + text) if text else ""
    return ctk.CTkButton(master, text=text, command=command, width=width, height=height,
                         corner_radius=8, font=F(12, "bold"), **{**_BTN[kind], **kw})


def card(master, **kw):
    return ctk.CTkFrame(master, fg_color=CARD, corner_radius=14, border_width=1,
                        border_color=BORDER, **kw)


def keycap(master, text, width=90):
    return ctk.CTkLabel(master, text=text, width=width, height=30, corner_radius=7,
                        fg_color=ACCENT_SOFT, text_color=ACCENT, font=F(12, "bold"))


def section_label(master, text, **pack):
    lbl = ctk.CTkLabel(master, text=text.upper(), font=F(10, "bold"), text_color=TEXT_FAINT,
                       anchor="w")
    lbl.pack(fill="x", **({"pady": (18, 8)} | pack))
    return lbl


def switch_row(master, title, desc, value, command):
    row = ctk.CTkFrame(master, fg_color="transparent")
    row.pack(fill="x", padx=20, pady=9)
    txt = ctk.CTkFrame(row, fg_color="transparent")
    txt.pack(side="left", fill="x", expand=True)
    ctk.CTkLabel(txt, text=title, font=F(13, "bold"), text_color=TEXT, anchor="w").pack(anchor="w")
    if desc:
        ctk.CTkLabel(txt, text=desc, font=F(11), text_color=TEXT_DIM, anchor="w",
                     justify="left", wraplength=560).pack(anchor="w")
    var = ctk.BooleanVar(value=value)
    ctk.CTkSwitch(row, text="", variable=var, width=46, progress_color=ACCENT,
                  command=lambda: command(var.get())).pack(side="right")
    return var


def divider(master):
    ctk.CTkFrame(master, height=1, fg_color=BORDER).pack(fill="x", padx=20)


def bind_tree(widgets, sequence, func):
    for w in widgets:
        try:
            w.bind(sequence, func, add="+")
        except (tk.TclError, NotImplementedError, ValueError):
            pass


def confirm(parent, title, message, ok_text="Confirmer", danger=False):
    """Boîte de confirmation modale au style de l'app. Retourne True/False."""
    top = ctk.CTkToplevel(parent)
    top.title(title)
    top.resizable(False, False)
    top.configure(fg_color=BG)
    owner = parent.winfo_toplevel()
    # Fenêtre principale cachée (zone de notification) : une boîte « transient » serait
    # invisible et bloquerait l'attente indéfiniment. On l'affiche alors au premier plan.
    if owner.winfo_viewable():
        top.transient(owner)
    else:
        top.attributes("-topmost", True)
    result = {"ok": False}
    ctk.CTkLabel(top, text=title, font=F(16, "bold"), text_color=TEXT).pack(anchor="w", padx=26, pady=(24, 6))
    ctk.CTkLabel(top, text=message, font=F(12), text_color=TEXT_DIM, justify="left",
                 wraplength=390, anchor="w").pack(anchor="w", padx=26)
    row = ctk.CTkFrame(top, fg_color="transparent")
    row.pack(side="bottom", fill="x", padx=26, pady=22)

    def done(ok):
        if not top.winfo_exists():  # Entrée + clic quasi simultanés
            return
        result["ok"] = ok
        top.destroy()

    button(row, ok_text, lambda: done(True), "danger" if danger else "primary").pack(side="right")
    button(row, "Annuler", lambda: done(False)).pack(side="right", padx=8)
    top.bind("<Escape>", lambda e: done(False))
    top.bind("<Return>", lambda e: done(True))
    # Hauteur adaptée au message (les notes de mise à jour débordaient d'une boîte fixe de 200 px).
    top.update_idletasks()
    w, h = 440, max(200, top.winfo_reqheight())
    if owner.winfo_viewable():
        x = owner.winfo_rootx() + (owner.winfo_width() - w) // 2
        y = owner.winfo_rooty() + (owner.winfo_height() - h) // 3
    else:
        x, y = (top.winfo_screenwidth() - w) // 2, (top.winfo_screenheight() - h) // 3
    top.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")
    top.after(60, lambda: top.winfo_exists() and (top.lift(), top.focus_force(), top.grab_set()))
    parent.wait_window(top)
    return result["ok"]


class Page(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent", corner_radius=0)
        self.app = app

    def header(self, title, subtitle=""):
        h = ctk.CTkFrame(self, fg_color="transparent")
        h.pack(fill="x", padx=32, pady=(28, 16))
        left = ctk.CTkFrame(h, fg_color="transparent")
        left.pack(side="left")
        ctk.CTkLabel(left, text=title, font=F(24, "bold"), text_color=TEXT).pack(anchor="w")
        sub = ctk.CTkLabel(left, text=subtitle, font=F(12), text_color=TEXT_DIM)
        sub.pack(anchor="w")
        # width/height=1 : un CTkFrame vide garde sinon 200x200 px et décale tout l'en-tête.
        right = ctk.CTkFrame(h, fg_color="transparent", width=1, height=1)
        right.pack(side="right")
        return sub, right

    def on_show(self):
        pass


# ============================================================
# PAGE PERSONNAGES
# ============================================================
class CharacterCard(ctk.CTkFrame):
    def __init__(self, master, page, w, n_ordered):
        super().__init__(master, fg_color=CARD, corner_radius=12, border_width=1,
                         border_color=BORDER)
        self.page, self.app, self.w = page, page.app, w
        self._active = False
        hwnd, order = w["hwnd"], w["order"]

        self.handle = ctk.CTkLabel(self, text="⋮⋮" if order else "", width=24, font=F(15),
                                   text_color=TEXT_FAINT, cursor="fleur" if order else "arrow")
        self.handle.pack(side="left", padx=(12, 2), pady=14)
        av = class_avatar(w["klass"], 52, order)
        if av:
            badge = ctk.CTkLabel(self, text="", image=av, width=52, height=52)
        else:  # classe inconnue : pastille numérotée
            badge = ctk.CTkLabel(self, text=str(order) if order else "–", width=38, height=38,
                                 corner_radius=19, font=F(15, "bold"),
                                 fg_color=order_color(order) if order else ("#E4E4EA", "#24242D"),
                                 text_color="white" if order else TEXT_FAINT)
        badge.pack(side="left", padx=(4, 14))

        info = ctk.CTkFrame(self, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, pady=10)
        name = ctk.CTkLabel(info, text=w["name"], font=F(15, "bold"), text_color=TEXT, anchor="w")
        name.pack(anchor="w")
        meta = ctk.CTkFrame(info, fg_color="transparent")
        meta.pack(anchor="w")
        clickables = [self, info, name, meta, badge]
        if w["klass"]:
            dot = ctk.CTkLabel(meta, text="●", font=F(10), text_color=class_color(w["klass"]))
            dot.pack(side="left")
            kl = ctk.CTkLabel(meta, text=w["klass"], font=F(11), text_color=TEXT_DIM)
            kl.pack(side="left", padx=(4, 0))
            clickables += [dot, kl]

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(side="right", padx=12)
        if order:
            button(actions, "", lambda: self.app.move(hwnd, -1), "subtle", width=32, ico="up",
                   state="disabled" if order == 1 else "normal").pack(side="left")
            button(actions, "", lambda: self.app.move(hwnd, +1), "subtle", width=32, ico="down",
                   state="disabled" if order == n_ordered else "normal").pack(side="left", padx=(0, 8))
            button(actions, "Afficher", lambda: self.app.focus_char(hwnd)).pack(side="left", padx=(0, 6))
            button(actions, "", self._menu_at_button, "subtle", width=32, ico="more").pack(side="left")
        else:
            button(actions, "Afficher", lambda: self.app.focus_char(hwnd)).pack(side="left", padx=(0, 6))
            button(actions, "Ajouter au cycle", lambda: self.app.add_to_cycle(hwnd),
                   "primary", ico="add").pack(side="left")

        self.active_lbl = ctk.CTkLabel(self, text="", font=F(11, "bold"), text_color=ACCENT)
        self.active_lbl.pack(side="right", padx=6)

        bind_tree(clickables, "<Double-Button-1>", lambda e: self.app.focus_char(hwnd))
        bind_tree(clickables + [self.handle], "<Button-3>", self._menu)
        if order:
            bind_tree([self.handle], "<ButtonPress-1>", lambda e: page.start_drag(self))
            bind_tree([self.handle], "<B1-Motion>", lambda e: page.drag_motion(e.y_root))
            bind_tree([self.handle], "<ButtonRelease-1>", lambda e: page.end_drag())

    def set_active(self, on):
        if on == self._active:
            return
        self._active = on
        self.configure(border_color=ACCENT if on else BORDER, fg_color=CARD_ACTIVE if on else CARD)
        self.active_lbl.configure(text="●  Au premier plan" if on else "")

    def set_drop(self, on):
        self.configure(border_color=ACCENT if on else BORDER,
                       fg_color=ACCENT_SOFT if on else (CARD_ACTIVE if self._active else CARD))

    def _menu_at_button(self):
        x, y = self.winfo_pointerxy()
        self._popup(x, y)

    def _menu(self, event):
        self._popup(event.x_root, event.y_root)

    def _popup(self, x, y):
        hwnd = self.w["hwnd"]
        opts = dict(tearoff=0, bg=resolve(CARD), fg=resolve(TEXT), activebackground=ACCENT,
                    activeforeground="white", bd=0, relief="flat", font=F(10))
        m = tk.Menu(self, **opts)
        m.add_command(label="Afficher la fenêtre", command=lambda: self.app.focus_char(hwnd))
        sub = tk.Menu(m, **opts)
        n = max(len([w for w in self.app.windows if w["order"] > 0]) + 1, 2)
        for pos in range(1, n + 1):
            sub.add_command(label=f"Position {pos}", command=lambda p=pos: self.app.move_to(hwnd, p))
        m.add_cascade(label="Déplacer en position", menu=sub)
        if self.w["order"]:
            m.add_command(label="Retirer du cycle", command=lambda: self.app.move_to(hwnd, 0))
        else:
            m.add_command(label="Ajouter au cycle", command=lambda: self.app.add_to_cycle(hwnd))
        m.add_separator()
        m.add_command(label="Copier le nom", command=lambda: (self.clipboard_clear(),
                                                               self.clipboard_append(self.w["name"])))
        try:
            m.tk_popup(x, y)
        finally:
            m.grab_release()


class WindowsPage(Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.sub, right = self.header("Personnages")
        button(right, "Actualiser", app.refresh, ico="refresh").pack(side="left", padx=(0, 8))
        self.apply_btn = button(right, "Activer le cyclage", app.apply_order, "primary", ico="play")
        self.apply_btn.pack(side="left")

        tb = ctk.CTkFrame(self, fg_color="transparent")
        tb.pack(fill="x", padx=32, pady=(0, 12))
        self.search = ctk.CTkEntry(tb, placeholder_text="Rechercher un personnage…  (Ctrl+F)",
                                   height=36, corner_radius=10, fg_color=CARD, border_color=BORDER,
                                   text_color=TEXT, font=F(12))
        self.search.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self._search_job = None
        self._last_query = ""
        self.search.bind("<KeyRelease>", lambda e: self._on_search())
        self.search.bind("<Escape>", lambda e: (self.search.delete(0, "end"), self._on_search(now=True)))
        self.preset_menu = ctk.CTkOptionMenu(tb, values=["—"], command=self._on_preset, height=36,
                                             width=210, corner_radius=10, font=F(12, "bold"),
                                             fg_color=CARD, button_color=CARD,
                                             button_hover_color=CARD_HOVER, text_color=TEXT,
                                             dropdown_font=F(12))
        self.preset_menu.pack(side="left", padx=(0, 8))
        self.layout_menu = ctk.CTkOptionMenu(tb, values=["—"], command=self._on_layout, height=36,
                                             width=170, corner_radius=10, font=F(12, "bold"),
                                             fg_color=CARD, button_color=CARD,
                                             button_hover_color=CARD_HOVER, text_color=TEXT,
                                             dropdown_font=F(12))
        self.layout_menu.pack(side="left", padx=(0, 8))
        self._layout_choices = []
        button(tb, "Tout retirer", app.reset_order, "subtle").pack(side="left")

        self.banner = ctk.CTkLabel(self, text="", fg_color=DANGER_SOFT, text_color=DANGER,
                                   corner_radius=10, font=F(11, "bold"), anchor="w", height=36)
        self.list = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=0)
        self.list.pack(fill="both", expand=True, padx=(32, 18), pady=(0, 6))
        ctk.CTkLabel(self, text="⋮⋮  Glisser pour réordonner    ·    Double-clic : afficher la "
                                "fenêtre    ·    Clic droit : plus d'options",
                     font=F(11), text_color=TEXT_FAINT).pack(pady=(0, 14))
        self.cards = {}
        self._drag = self._target = None

    def on_show(self):
        self.refresh_presets()
        self.refresh_layouts()

    def _on_search(self, now=False):
        # Anti-rebond : on ne reconstruit la liste qu'une fois la frappe terminée, et
        # seulement si le texte a changé (flèches, Maj… ne déclenchent plus de rendu).
        if self._search_job:
            self.after_cancel(self._search_job)
            self._search_job = None
        q = self.search.get().strip().lower()
        if q == self._last_query:
            return
        if now:
            self._last_query = q
            self.render()
        else:
            self._search_job = self.after(150, lambda: self._on_search(now=True))

    def refresh_layouts(self):
        self._layout_choices = self.app.layout_choices()
        self.layout_menu.configure(values=[c[0] for c in self._layout_choices])
        self.layout_menu.set("▦  Disposition")

    def _on_layout(self, label):
        choice = next((c for c in self._layout_choices if c[0] == label), None)
        self.layout_menu.set("▦  Disposition")
        if choice:
            self.app.arrange(choice[1], choice[2])

    def refresh_presets(self):
        names = list(self.app.presets.keys()) or ["Aucun preset"]
        self.preset_menu.configure(values=names)
        self.preset_menu.set("★  Appliquer un preset")

    def _on_preset(self, name):
        if name in self.app.presets:
            self.app.apply_preset(name)
        self.preset_menu.set("★  Appliquer un preset")

    def set_banner(self, text):
        if text:
            self.banner.configure(text="   ⚠  " + text)
            self.banner.pack(fill="x", padx=32, pady=(0, 10), before=self.list)
        else:
            self.banner.pack_forget()

    def render(self):
        # Un rafraîchissement auto pendant un glisser-déposer détruit les cartes : on abandonne le drag.
        self._drag = self._target = None
        for ch in self.list.winfo_children():
            ch.destroy()
        self.cards = {}
        q = self.search.get().strip().lower()
        self._last_query = q
        wins = [w for w in self.app.windows if not q or q in w["title"].lower()]
        ordered = [w for w in wins if w["order"] > 0]
        others = [w for w in wins if w["order"] <= 0]
        n_ordered = len([w for w in self.app.windows if w["order"] > 0])

        if not wins:
            box = ctk.CTkFrame(self.list, fg_color="transparent")
            box.pack(fill="x", pady=70)
            ctk.CTkLabel(box, text="", image=icon("search" if q else "game", 48, TEXT_FAINT)).pack()
            ctk.CTkLabel(box, text="Aucun résultat" if q else "Aucune fenêtre Dofus détectée",
                         font=F(16, "bold"), text_color=TEXT).pack(pady=(8, 2))
            ctk.CTkLabel(box, text="Essayez un autre nom." if q else
                         "Lancez vos comptes : ils apparaîtront ici automatiquement.",
                         font=F(12), text_color=TEXT_DIM).pack()
        for title, group in (("Dans le cycle", ordered), ("Hors cycle", others)):
            if not group:
                continue
            section_label(self.list, f"{title}  ·  {len(group)}",
                          pady=(4 if title == "Dans le cycle" or not ordered else 18, 8))
            for w in group:
                c = CharacterCard(self.list, self, w, n_ordered)
                c.pack(fill="x", pady=4)
                self.cards[w["hwnd"]] = c
        self.update_header()
        self.highlight(self.app.foreground)

    def update_header(self):
        n = len(self.app.windows)
        k = len([w for w in self.app.windows if w["order"] > 0])
        txt = f"{n} fenêtre{'s' if n > 1 else ''} détectée{'s' if n > 1 else ''}"
        if k:
            txt += f"  ·  {k} dans le cycle"
        self.sub.configure(text=txt)
        if self.app.cycle_active:
            self.apply_btn.configure(text="  Cyclage actif", image=icon("check", 15, "white"),
                                     fg_color=SUCCESS, hover_color="#35A045")
        else:
            self.apply_btn.configure(text="  Activer le cyclage", image=icon("play", 15, "white"),
                                     fg_color=ACCENT, hover_color=ACCENT_HOVER)

    def highlight(self, fg):
        for hwnd, c in self.cards.items():
            c.set_active(hwnd == fg)

    # ---- Drag & drop ----
    def start_drag(self, c):
        self._drag, self._target = c, None
        c.configure(border_color=ACCENT)

    def drag_motion(self, y_root):
        if not self._drag or not self._drag.winfo_exists():
            return
        target = None
        for c in self.cards.values():
            if c is self._drag or c.w["order"] <= 0:
                continue
            top = c.winfo_rooty()
            if top <= y_root <= top + c.winfo_height():
                target = c
                break
        if target is not self._target:
            if self._target:
                self._target.set_drop(False)
            self._target = target
            if target:
                target.set_drop(True)

    def end_drag(self):
        src, dst = self._drag, self._target
        self._drag = self._target = None
        if src and not src.winfo_exists():
            return
        if dst and not dst.winfo_exists():
            dst = None
        if src and dst:
            self.app.move_to(src.w["hwnd"], dst.w["order"])
        elif src:
            src.set_drop(False)


# ============================================================
# PAGE PRESETS
# ============================================================
class PresetEditDialog(ctk.CTkToplevel):
    def __init__(self, parent, app, name="", names=None, on_save=None):
        super().__init__(parent)
        self.app, self.on_save, self.orig = app, on_save, name
        self.title("Modifier le preset" if name else "Nouveau preset")
        self.geometry("460x520")
        self.minsize(420, 460)
        self.configure(fg_color=BG)
        self.transient(parent.winfo_toplevel())

        ctk.CTkLabel(self, text=self.title(), font=F(18, "bold"), text_color=TEXT).pack(anchor="w", padx=26, pady=(24, 14))
        ctk.CTkLabel(self, text="Nom", font=F(11, "bold"), text_color=TEXT_DIM).pack(anchor="w", padx=26)
        self.name = ctk.CTkEntry(self, height=36, corner_radius=8, fg_color=CARD, border_color=BORDER,
                                 text_color=TEXT, font=F(12))
        self.name.insert(0, name)
        self.name.pack(fill="x", padx=26, pady=(4, 14))
        ctk.CTkLabel(self, text="Personnages, dans l'ordre (un par ligne)", font=F(11, "bold"),
                     text_color=TEXT_DIM).pack(anchor="w", padx=26)
        self.box = ctk.CTkTextbox(self, corner_radius=8, fg_color=CARD, border_color=BORDER,
                                  border_width=1, text_color=TEXT, font=F(13))
        self.box.pack(fill="both", expand=True, padx=26, pady=(4, 8))
        self.box.insert("1.0", "\n".join(names or []))
        button(self, "Remplir avec l'ordre actuel", self._fill_current, "subtle").pack(anchor="w", padx=20)

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=26, pady=20)
        button(row, "Enregistrer", self._save, "primary").pack(side="right")
        button(row, "Annuler", self.destroy).pack(side="right", padx=8)
        self.bind("<Escape>", lambda e: self.destroy())
        self.name.bind("<Return>", lambda e: self.box.focus_set())
        self.after(60, lambda: self.winfo_exists() and (self.lift(), self.focus_force(),
                                                        self.name.focus_set(), self.grab_set()))

    def _fill_current(self):
        cur = [w["name"] for w in sorted(self.app.windows, key=lambda w: w["order"]) if w["order"] > 0]
        self.box.delete("1.0", "end")
        self.box.insert("1.0", "\n".join(cur))

    def _save(self):
        name = self.name.get().strip()
        # Casse alignée sur les persos connus (« schokoarc » -> « Schokoarc ») et doublons retirés :
        # un même nom deux fois laissait des trous dans la numérotation du cycle.
        known = {n.lower(): n for n in self.app.known_chars()}
        names, seen = [], set()
        for n in self.box.get("1.0", "end").splitlines():
            n = n.strip()
            if n and n.lower() not in seen:
                seen.add(n.lower())
                names.append(known.get(n.lower(), n))
        if not name:
            self.app.toast("Donnez un nom au preset.", "warning")
            return
        if not names:
            self.app.toast("Ajoutez au moins un personnage.", "warning")
            return
        if name != self.orig and name in self.app.presets:
            if not confirm(self, "Écraser ?", f"Un preset « {name} » existe déjà. Le remplacer ?",
                           "Remplacer", danger=True):
                return
        unknown = [n for n in names if n.lower() not in known]
        self.destroy()
        self.on_save(self.orig, name, names)
        if unknown:
            self.app.toast("Jamais vu" + ("s" if len(unknown) > 1 else "") + " : " + ", ".join(unknown)
                           + " — vérifiez l'orthographe.", "warning")


class PresetsPage(Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.sub, right = self.header("Presets d'équipe",
                                      "Enregistrez vos compositions et appliquez-les en un clic.")
        button(right, "Nouveau", lambda: self.edit(), ico="add").pack(side="left", padx=(0, 8))
        button(right, "Enregistrer l'ordre actuel", self.save_current, "primary",
               ico="save").pack(side="left")
        self.grid_frame = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=0)
        self.grid_frame.pack(fill="both", expand=True, padx=(32, 18), pady=(0, 16))
        self.grid_frame.grid_columnconfigure((0, 1), weight=1, uniform="p")

    def on_show(self):
        self.render()

    def render(self):
        for ch in self.grid_frame.winfo_children():
            ch.destroy()
        presets = self.app.presets
        online = {w["name"].lower() for w in self.app.windows}
        if not presets:
            box = ctk.CTkFrame(self.grid_frame, fg_color="transparent")
            box.grid(row=0, column=0, columnspan=2, pady=80)
            ctk.CTkLabel(box, text="★", font=F(40), text_color=ACCENT).pack()
            ctk.CTkLabel(box, text="Aucun preset", font=F(16, "bold"), text_color=TEXT).pack(pady=(6, 2))
            ctk.CTkLabel(box, text="Placez vos personnages dans l'ordre voulu puis cliquez sur "
                                   "« Enregistrer l'ordre actuel ».", font=F(12), text_color=TEXT_DIM).pack()
            return
        for i, (name, names) in enumerate(presets.items()):
            c = card(self.grid_frame)
            c.grid(row=i // 2, column=i % 2, sticky="nsew", padx=6, pady=6)
            top = ctk.CTkFrame(c, fg_color="transparent")
            top.pack(fill="x", padx=18, pady=(16, 8))
            ctk.CTkLabel(top, text=name, font=F(16, "bold"), text_color=TEXT).pack(side="left")
            if config.active_preset == name:
                ctk.CTkLabel(top, text=" Par défaut ", font=F(10, "bold"), fg_color=ACCENT_SOFT,
                             text_color=ACCENT, corner_radius=6, height=22).pack(side="left", padx=8)
            pk = config.preset_keys.get(name)
            if pk:
                ctk.CTkLabel(top, text=" " + core.combo_name(pk["vkey"], pk["mods"]) + " ", font=F(10, "bold"),
                             fg_color=CARD_HOVER, text_color=TEXT_DIM, corner_radius=6,
                             height=22).pack(side="left", padx=4)
            k = sum(1 for n in names if n.lower() in online)
            ctk.CTkLabel(top, text=f"{k}/{len(names)} connecté{'s' if k > 1 else ''}", font=F(11, "bold"),
                         text_color=SUCCESS if k == len(names) else (WARNING if k else TEXT_FAINT)
                         ).pack(side="right")

            chips = ctk.CTkFrame(c, fg_color="transparent")
            chips.pack(fill="x", padx=18, pady=(0, 12))
            for j, n in enumerate(names):
                row = ctk.CTkFrame(chips, fg_color="transparent")
                row.pack(anchor="w", pady=2)
                av = class_avatar(self.app.class_of(n), 28, j + 1)
                if av:
                    ctk.CTkLabel(row, text="", image=av, width=28, height=28).pack(side="left")
                else:
                    ctk.CTkLabel(row, text=str(j + 1), width=22, height=22, corner_radius=11,
                                 fg_color=order_color(j + 1), text_color="white",
                                 font=F(10, "bold")).pack(side="left")
                ctk.CTkLabel(row, text=n, font=F(12, "bold" if n.lower() in online else "normal"),
                             text_color=TEXT if n.lower() in online else TEXT_FAINT).pack(side="left", padx=8)

            act = ctk.CTkFrame(c, fg_color="transparent")
            act.pack(fill="x", padx=18, pady=(0, 16))
            button(act, "Appliquer", lambda n=name: self.app.apply_preset(n), "primary").pack(side="left")
            button(act, "Modifier", lambda n=name: self.edit(n)).pack(side="left", padx=6)
            is_def = config.active_preset == name
            button(act, "Retirer défaut" if is_def else "Par défaut",
                   lambda n=name, d=is_def: self.app.set_default_preset("" if d else n),
                   "subtle").pack(side="left")
            button(act, "Supprimer", lambda n=name: self.delete(n), "danger").pack(side="right")

    def edit(self, name=""):
        PresetEditDialog(self, self.app, name, self.app.presets.get(name, []), self.app.save_preset)

    def save_current(self):
        cur = [w["name"] for w in sorted(self.app.windows, key=lambda w: w["order"]) if w["order"] > 0]
        if not cur:
            self.app.toast("Placez d'abord des personnages dans le cycle.", "warning")
            return
        PresetEditDialog(self, self.app, "", cur, self.app.save_preset)

    def delete(self, name):
        if confirm(self, "Supprimer le preset", f"Supprimer définitivement « {name} » ?",
                   "Supprimer", danger=True):
            self.app.delete_preset(name)


# ============================================================
# PAGE STATISTIQUES
# ============================================================
def fmt_duration(sec):
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s"


class StatsPage(Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.sub, right = self.header("Statistiques", "Session en cours")
        self.period = "session"
        self._periods = {"Session": "session", "Aujourd'hui": 1, "7 jours": 7, "Total": None}
        seg = ctk.CTkSegmentedButton(right, values=list(self._periods), font=F(12, "bold"), height=34,
                                     selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
                                     command=self._on_period)
        seg.set("Session")
        seg.pack(side="left", padx=(0, 10))
        button(right, "Exporter CSV", self.export_csv, ico="save").pack(side="left", padx=(0, 8))
        self.reset_btn = button(right, "Réinitialiser", self.reset, "danger")
        self.reset_btn.pack(side="left")
        tiles = ctk.CTkFrame(self, fg_color="transparent")
        tiles.pack(fill="x", padx=26)
        tiles.grid_columnconfigure((0, 1, 2), weight=1, uniform="t")
        self.tiles, self.captions = {}, {}
        for i, (key, caption) in enumerate((("dur", "Durée de session"), ("sw", "Changements de fenêtre"),
                                            ("chars", "Personnages joués"))):
            t = card(tiles)
            t.grid(row=0, column=i, sticky="nsew", padx=6)
            v = ctk.CTkLabel(t, text="—", font=F(26, "bold"), text_color=TEXT)
            v.pack(anchor="w", padx=20, pady=(16, 0))
            cap = ctk.CTkLabel(t, text=caption, font=F(11), text_color=TEXT_DIM)
            cap.pack(anchor="w", padx=20, pady=(0, 16))
            self.tiles[key], self.captions[key] = v, cap
        section_label(self, "Temps par personnage", padx=32, pady=(22, 8))
        self.box = card(self)
        self.box.pack(fill="both", expand=True, padx=32, pady=(0, 20))
        self.rows = {}
        self._job = None

    def on_show(self):
        # Au moment d'on_show la page vient d'être packée mais n'est pas encore « mappée » :
        # on rend immédiatement, le test de visibilité ne vaut que pour les ticks suivants.
        if self._job:
            self.after_cancel(self._job)
        self.render()
        self._job = self.after(1000, self._tick)

    def _tick(self):
        self._job = None
        if not self.winfo_ismapped():
            return
        self.render()
        self._job = self.after(1000, self._tick)

    def _on_period(self, label):
        self.period = self._periods[label]
        self.sub.configure(text={"session": "Session en cours", 1: "Aujourd'hui", 7: "7 derniers jours",
                                 None: "Depuis le début"}[self.period])
        self.reset_btn.configure(text="Réinitialiser" if self.period == "session" else "Effacer l'historique")
        self.captions["dur"].configure(text="Durée de session" if self.period == "session" else "Temps de jeu")
        self.rows = {"__force__": None}
        self.render()

    def render(self):
        if self.period == "session":
            snap, switches, dur = core.stats.snapshot(), core.stats.switches, core.stats.duration()
        else:
            snap, switches = core.stats.totals(self.period)
            dur = sum(v["seconds"] for v in snap.values())
        self.tiles["dur"].configure(text=fmt_duration(dur))
        self.tiles["sw"].configure(text=str(switches))
        self.tiles["chars"].configure(text=str(len(snap)))
        items = sorted(snap.items(), key=lambda x: -x[1]["seconds"])
        if [n for n, _ in items] != list(self.rows):
            for ch in self.box.winfo_children():
                ch.destroy()
            self.rows = {}
            if not items:
                ctk.CTkLabel(self.box, text="Aucun changement de fenêtre pour l'instant.",
                             font=F(12), text_color=TEXT_DIM).pack(pady=50)
            for i, (name, _) in enumerate(items):
                r = ctk.CTkFrame(self.box, fg_color="transparent")
                r.pack(fill="x", padx=20, pady=(14 if i == 0 else 6, 6))
                top = ctk.CTkFrame(r, fg_color="transparent")
                top.pack(fill="x")
                av = class_avatar(self.app.class_of(name), 26)
                ctk.CTkLabel(top, text=("  " + name) if av else name, image=av, compound="left",
                             font=F(13, "bold"), text_color=TEXT).pack(side="left")
                val = ctk.CTkLabel(top, text="", font=F(11), text_color=TEXT_DIM)
                val.pack(side="right")
                bar = ctk.CTkProgressBar(r, height=8, corner_radius=4, fg_color=BORDER,
                                         progress_color=order_color(i + 1))
                bar.pack(fill="x", pady=(6, 0))
                self.rows[name] = (val, bar)
        total = sum(v["seconds"] for v in snap.values()) or 1
        for name, (val, bar) in self.rows.items():
            d = snap[name]
            pct = d["seconds"] / total
            val.configure(text=f"{fmt_duration(d['seconds'])}  ·  {pct * 100:.0f} %  ·  {d['count']} focus")
            bar.set(pct)

    def reset(self):
        if self.period == "session":
            if confirm(self, "Réinitialiser la session", "Remettre à zéro les compteurs de la session ?\n"
                       "L'historique des jours précédents est conservé.", "Réinitialiser", danger=True):
                core.stats.reset()
        elif confirm(self, "Effacer l'historique", "Supprimer définitivement tout l'historique des "
                     "statistiques ?", "Effacer", danger=True):
            core.stats.clear_history()
        self.rows = {"__force__": None}
        self.render()

    def export_csv(self):
        fp = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", initialfile="dofus_stats.csv",
                                          filetypes=[("CSV", "*.csv")], title="Exporter les statistiques")
        if not fp:
            return
        core.stats.flush()
        try:
            with open(fp, "w", newline="", encoding="utf-8-sig") as f:  # BOM : accents OK dans Excel
                w = csv.writer(f, delimiter=";")
                w.writerow(["Date", "Personnage", "Temps (s)", "Temps", "Focus"])
                for day, d in sorted(core.stats.history["days"].items()):
                    for n, v in sorted(d.get("chars", {}).items()):
                        w.writerow([day, n, int(v["seconds"]), fmt_duration(v["seconds"]), v["count"]])
            self.app.toast(f"Statistiques exportées vers {os.path.basename(fp)}.")
        except OSError as e:
            self.app.toast(f"Export impossible : {e}", "error")


# ============================================================
# PAGE RACCOURCIS
# ============================================================
class HotkeysPage(Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.header("Raccourcis", "Touches globales, actives même quand le jeu a le focus.")
        self.banner = ctk.CTkLabel(self, text="", fg_color=DANGER_SOFT, text_color=DANGER,
                                   corner_radius=10, font=F(11, "bold"), anchor="w", justify="left")
        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=0)
        self.body.pack(fill="both", expand=True, padx=(32, 18), pady=(0, 16))
        self.render()

    def on_show(self):
        self.render()

    def set_failed(self, failed):
        if failed:
            self.banner.configure(text="   ⚠  Non disponibles (utilisés par une autre application) : "
                                       + ", ".join(failed))
            self.banner.pack(fill="x", padx=32, pady=(0, 10), before=self.body, ipady=8)
        else:
            self.banner.pack_forget()

    def _row(self, master, title, desc, combo, on_edit, on_clear=None, extra=None):
        row = ctk.CTkFrame(master, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=10)
        txt = ctk.CTkFrame(row, fg_color="transparent")
        txt.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(txt, text=title, font=F(13, "bold"), text_color=TEXT, anchor="w").pack(anchor="w")
        if desc:
            ctk.CTkLabel(txt, text=desc, font=F(11), text_color=TEXT_DIM, anchor="w").pack(anchor="w")
        if on_clear:
            button(row, "✕", on_clear, "subtle", width=32).pack(side="right")
        button(row, "Modifier", on_edit).pack(side="right", padx=8)
        keycap(row, core.combo_name(*combo), width=120).pack(side="right")
        if extra:
            extra(row).pack(side="right", padx=(0, 12))

    def _target_menu(self, row, i, d, choices):
        def pick(v):
            target = f"pos:{v.split()[-1]}" if v.startswith("Position ") else f"char:{v}"
            self.after(10, lambda: self.app.set_direct_target(i, target))

        m = ctk.CTkOptionMenu(row, values=choices, width=160, height=30, corner_radius=8, font=F(12),
                              fg_color=CARD_HOVER, button_color=CARD_HOVER, button_hover_color=BORDER,
                              text_color=TEXT, dropdown_font=F(12), command=pick)
        m.set(core.target_label(d["target"]))
        return m

    def render(self):
        # Conserve la position de défilement : sinon chaque modification de touche remonte en haut.
        canvas = getattr(self.body, "_parent_canvas", None)
        try:
            y = canvas.yview()[0] if canvas else 0.0
        except tk.TclError:
            y = 0.0
        for ch in self.body.winfo_children():
            ch.destroy()
        self._build_rows()
        if canvas and y:
            self.after_idle(lambda: canvas.winfo_exists() and canvas.yview_moveto(y))

    def _build_rows(self):
        section_label(self.body, "Navigation", pady=(0, 8))
        c = card(self.body)
        c.pack(fill="x")
        self._row(c, "Personnage suivant", "Passe à la fenêtre suivante du cycle.",
                  (config.vkey_next, config.mods_next), lambda: self._capture("next"))
        divider(c)
        self._row(c, "Personnage précédent", "Revient à la fenêtre précédente du cycle.",
                  (config.vkey_prev, config.mods_prev), lambda: self._capture("prev"))

        section_label(self.body, "Accès direct")
        c = card(self.body)
        c.pack(fill="x")
        if not config.direct_keys:
            ctk.CTkLabel(c, text="Aucun raccourci direct. Associez une touche à une position du cycle "
                                 "ou directement à un personnage.",
                         font=F(12), text_color=TEXT_DIM).pack(anchor="w", padx=20, pady=(16, 4))
        choices = [f"Position {n}" for n in range(1, 9)] + self.app.known_chars()
        for i, d in enumerate(config.direct_keys):
            if i:
                divider(c)
            kind, _, val = d["target"].partition(":")
            desc = (f"Affiche {val}, même s'il n'est pas dans le cycle." if kind == "char"
                    else f"Affiche la position {val} du cycle.")
            self._row(c, core.target_label(d["target"]), desc, (d["vkey"], d["mods"]),
                      lambda i=i: self._capture(("direct", i)),
                      lambda i=i: self.app.remove_direct_key(i),
                      extra=lambda row, i=i, d=d: self._target_menu(row, i, d, choices))
        button(c, "Ajouter un raccourci direct", lambda: self._capture(("direct", len(config.direct_keys))),
               "subtle", ico="add").pack(anchor="w", padx=14, pady=(8, 14))

        section_label(self.body, "Presets")
        c = card(self.body)
        c.pack(fill="x")
        if not self.app.presets:
            ctk.CTkLabel(c, text="Aucun preset. Créez-en un dans la page Presets.", font=F(12),
                         text_color=TEXT_DIM).pack(anchor="w", padx=20, pady=16)
        for j, name in enumerate(self.app.presets):
            if j:
                divider(c)
            k = config.preset_keys.get(name)
            self._row(c, name, "Applique ce preset, active le cyclage et affiche le 1er personnage.",
                      (k["vkey"], k["mods"]) if k else (0, 0),
                      lambda n=name: self._capture(("preset", n)),
                      (lambda n=name: self.app.set_hotkey(("preset", n), None)) if k else None)

        section_label(self.body, "Pause")
        c = card(self.body)
        c.pack(fill="x")
        self.pause_var = switch_row(c, "Mettre les raccourcis en pause",
                                    "Libère les touches (pour écrire dans le chat, par ex.). "
                                    "Aussi accessible depuis la barre latérale et l'icône de notification.",
                                    self.app.paused, self.app.set_paused)
        ctk.CTkLabel(self.body, text="Astuce : les touches F13 à F24 sont idéales sur une souris ou un "
                                     "clavier programmable — elles n'entrent jamais en conflit avec le jeu.",
                     font=F(11), text_color=TEXT_FAINT, wraplength=700, justify="left"
                     ).pack(anchor="w", pady=(16, 0))

    def _capture(self, slot):
        KeyCaptureDialog(self, self.app.slot_label(slot), lambda combo: self.app.set_hotkey(slot, combo),
                         allow_clear=isinstance(slot, tuple))


# ============================================================
# PAGE PARAMÈTRES
# ============================================================
class SettingsPage(Page):
    def on_show(self):
        self.max_var.set(config.auto_maximize)  # peut être modifié par la mosaïque

    def __init__(self, master, app):
        super().__init__(master, app)
        self.header("Paramètres")
        body = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=0)
        body.pack(fill="both", expand=True, padx=(32, 18), pady=(0, 16))
        a = app

        section_label(body, "Apparence", pady=(0, 8))
        c = card(body)
        c.pack(fill="x")
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=16)
        ctk.CTkLabel(row, text="Thème", font=F(13, "bold"), text_color=TEXT).pack(side="left")
        labels = {"dark": "Sombre", "light": "Clair", "system": "Système"}
        seg = ctk.CTkSegmentedButton(row, values=list(labels.values()), font=F(12, "bold"), height=32,
                                     selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
                                     command=lambda v: a.set_theme({v2: k for k, v2 in labels.items()}[v]))
        seg.set(labels.get(config.theme, "Sombre"))
        seg.pack(side="right")

        section_label(body, "Changement de fenêtre")
        c = card(body)
        c.pack(fill="x")
        self.max_var = switch_row(c, "Maximiser la fenêtre affichée",
                   "Recommandé en plein écran. Désactivé automatiquement quand vous utilisez la mosaïque.",
                   config.auto_maximize, lambda v: a.set_option("auto_maximize", v))
        divider(c)
        switch_row(c, "Afficher le nom du personnage à l'écran",
                   "Petit bandeau en haut de l'écran à chaque changement. Ne prend jamais le focus.",
                   config.show_overlay, lambda v: a.set_option("show_overlay", v))
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(0, 14))
        ctk.CTkLabel(row, text="Durée d'affichage", font=F(12), text_color=TEXT_DIM).pack(side="left")
        val = ctk.CTkLabel(row, text=f"{config.overlay_ms / 1000:.1f} s", font=F(12, "bold"),
                           text_color=TEXT, width=50)
        val.pack(side="right")
        sl = ctk.CTkSlider(row, from_=400, to=3000, number_of_steps=26, button_color=ACCENT,
                           button_hover_color=ACCENT_HOVER, progress_color=ACCENT,
                           command=lambda v: (val.configure(text=f"{v / 1000:.1f} s"),
                                              a.set_option("overlay_ms", int(v), save=False)))
        sl.set(config.overlay_ms)
        sl.bind("<ButtonRelease-1>", lambda e: config.save())
        sl.pack(side="right", fill="x", expand=True, padx=16)
        button(row, "Tester", a.test_overlay, "subtle").pack(side="right")

        section_label(body, "Application")
        c = card(body)
        c.pack(fill="x")
        rows = [
            ("Notifications", "Confirmations discrètes en bas de la fenêtre.", "show_notifs"),
            ("Toujours au premier plan", "Garde le manager au-dessus des autres fenêtres.", "always_on_top"),
            ("Réduire dans la zone de notification", "Fermer la fenêtre garde le manager actif en arrière-plan.",
             "minimize_to_tray"),
            ("Démarrer réduit", "Au lancement, ne pas afficher la fenêtre (icône de notification seulement).",
             "start_minimized"),
            ("Reprendre le cyclage automatiquement", "Au démarrage, réapplique l'ordre mémorisé ou le preset "
                                                     "par défaut dès que les personnages sont détectés.",
             "auto_apply_last"),
        ]
        for i, (t, d, key) in enumerate(rows):
            if i:
                divider(c)
            switch_row(c, t, d, getattr(config, key), lambda v, k=key: a.set_option(k, v))
        divider(c)
        switch_row(c, "Démarrer avec Windows", "Lance le manager à l'ouverture de session.",
                   core.is_startup_enabled(), a.set_startup)

        section_label(body, "Données")
        c = card(body)
        c.pack(fill="x")
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=16)
        button(row, "Exporter l'ordre", a.export_layout).pack(side="left")
        button(row, "Importer", a.import_layout).pack(side="left", padx=8)
        button(row, "Ouvrir le dossier", lambda: os.startfile(core.APP_DIR), "subtle").pack(side="right")

        section_label(body, "À propos")
        c = card(body)
        c.pack(fill="x")
        ctk.CTkLabel(c, text=f"{core.APP_NAME}  ·  v{core.APP_VERSION}", font=F(13, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=20, pady=(16, 0))
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(0, 8))
        ctk.CTkLabel(row, text=f"Créé par {core.APP_AUTHOR}", font=F(12, "bold"),
                     text_color=ACCENT).pack(side="left")
        button(row, "Vérifier les mises à jour", a.check_update_now, "subtle").pack(side="right")
        ctk.CTkLabel(c, text="Gestionnaire de fenêtres multi-comptes pour Dofus 3. Utilise uniquement les "
                             "fonctions de fenêtrage de Windows : aucune lecture ni écriture dans la mémoire "
                             "du jeu, aucune injection, aucune automatisation d'actions en jeu.",
                     font=F(11), text_color=TEXT_DIM, wraplength=680, justify="left"
                     ).pack(anchor="w", padx=20, pady=(0, 10))
        ctk.CTkLabel(c, text=f"{core.COPYRIGHT}. Tous droits réservés.", font=F(11),
                     text_color=TEXT_FAINT).pack(anchor="w", padx=20, pady=(0, 16))
