# -*- coding: utf-8 -*-
"""Dofus Manager — palette, icône, overlay de changement, toasts, capture de touches."""
import os
import sys
import tkinter as tk
import unicodedata

import customtkinter as ctk
import win32con
import win32gui
from PIL import Image, ImageDraw, ImageFont, ImageTk

import dm_core as core

# ============================================================
# PALETTE — tuples (clair, sombre) : le changement de thème est instantané
# ============================================================
BG          = ("#F4F4F7", "#0E0E12")
SIDEBAR     = ("#ECECF1", "#131318")
CARD        = ("#FFFFFF", "#17171E")
CARD_HOVER  = ("#F5F5F9", "#1E1E27")
CARD_ACTIVE = ("#F1EDFF", "#1F1A36")
BORDER      = ("#E2E2EA", "#262630")
TEXT        = ("#16161D", "#ECECF1")
TEXT_DIM    = ("#5F5F6E", "#9A9AA8")
TEXT_FAINT  = ("#9A9AA8", "#5E5E6B")
ACCENT      = "#7C5CFF"
ACCENT_HOVER = "#6A4BEE"
ACCENT_SOFT = ("#EEE9FF", "#231C40")
SUCCESS     = "#3FB950"
WARNING     = "#D29922"
DANGER      = "#F85149"
DANGER_SOFT = ("#FDECEC", "#2D1618")

ORDER_COLORS = ["#7C5CFF", "#3FB950", "#58A6FF", "#F0883E",
                "#DB61A2", "#D29922", "#F85149", "#A371F7"]

CLASS_COLORS = {
    "feca": "#D4A017", "osamodas": "#4FA3D1", "enutrof": "#C9A227", "sram": "#8E8E99",
    "xelor": "#3D7DD8", "ecaflip": "#E0584F", "eniripsa": "#E86FA8", "iop": "#E8503A",
    "cra": "#5DAE4B", "sadida": "#3FA34D", "sacrieur": "#C0392B", "pandawa": "#6BAF92",
    "roublard": "#5A6ACF", "zobal": "#9B59B6", "steamer": "#2E86AB", "eliotrope": "#1ABC9C",
    "huppermage": "#8E44AD", "ouginak": "#A0522D", "forgelance": "#607D8B",
}

FONT = "Segoe UI"


def F(size=13, weight="normal"):
    return (FONT, size, weight)


def order_color(order):
    return ORDER_COLORS[(order - 1) % len(ORDER_COLORS)] if order > 0 else "#5E5E6B"


def class_color(klass):
    return CLASS_COLORS.get((klass or "").split(" ")[0].lower(), "#7A7A88")


def resolve(color):
    """Couleur effective (hex) d'un tuple (clair, sombre) selon le thème courant."""
    if isinstance(color, (tuple, list)):
        return color[1] if ctk.get_appearance_mode() == "Dark" else color[0]
    return color


# ============================================================
# ICÔNES VECTORIELLES (police Segoe Fluent Icons / MDL2 de Windows)
# ============================================================
_ICON_FONT = next((p for p in (r"C:\Windows\Fonts\SegoeIcons.ttf", r"C:\Windows\Fonts\segmdl2.ttf")
                   if os.path.exists(p)), None)
ICONS = {"people": "\uE716", "star": "\uE734", "stats": "\uE9D9", "keyboard": "\uE765",
         "settings": "\uE713", "refresh": "\uE72C", "play": "\uE768", "pause": "\uE769",
         "save": "\uE74E", "add": "\uE710", "check": "\uE73E", "up": "\uE70E", "down": "\uE70D",
         "more": "\uE712", "game": "\uE7FC", "search": "\uE721", "delete": "\uE74D", "edit": "\uE70F"}
_icon_cache = {}


def _glyph(char, size, color):
    s = 4
    img = Image.new("RGBA", (size * s, size * s), (0, 0, 0, 0))
    fnt = ImageFont.truetype(_ICON_FONT, int(size * s * 0.92))
    ImageDraw.Draw(img).text((size * s / 2, size * s / 2), char, font=fnt, fill=color, anchor="mm")
    return img.resize((size, size), Image.LANCZOS)


def icon(name, size=16, color=TEXT_DIM):
    """CTkImage (variantes clair/sombre) ou None si la police d'icônes est absente."""
    if not _ICON_FONT or name not in ICONS:
        return None
    key = (name, size, str(color))
    if key not in _icon_cache:
        light, dark = (color, color) if isinstance(color, str) else color
        _icon_cache[key] = ctk.CTkImage(light_image=_glyph(ICONS[name], size, light),
                                        dark_image=_glyph(ICONS[name], size, dark), size=(size, size))
    return _icon_cache[key]


# ============================================================
# AVATARS DE CLASSE (illustrations officielles © Ankama, assets/classes/<id>.jpg)
# ============================================================
CLASS_IDS = {"feca": 1, "osamodas": 2, "enutrof": 3, "sram": 4, "xelor": 5, "ecaflip": 6,
             "eniripsa": 7, "iop": 8, "cra": 9, "sadida": 10, "sacrieur": 11, "pandawa": 12,
             "roublard": 13, "zobal": 14, "steamer": 15, "eliotrope": 16, "huppermage": 17,
             "ouginak": 18, "forgelance": 20}
_src_cache, _avatar_cache = {}, {}


def _asset_path(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))  # exe ou sources
    return os.path.join(base, "assets", *parts)


def class_id(klass):
    k = unicodedata.normalize("NFKD", (klass or "").split(" ")[0]).encode("ascii", "ignore").decode()
    return CLASS_IDS.get(k.lower())


def _class_source(cid):
    if cid not in _src_cache:
        path = _asset_path("classes", f"{cid}.jpg")
        _src_cache[cid] = Image.open(path).convert("RGB") if os.path.exists(path) else None
    return _src_cache[cid]


def class_avatar_pil(klass, size, order=0):
    """Portrait rond de la classe, cerclé de la couleur de position, pastille n° en bas à droite."""
    cid = class_id(klass)
    src = _class_source(cid) if cid else None
    if src is None:
        return None
    big = size * 4
    w, h = src.size
    side = int(h * 0.80)                        # cadrage sur le visage (haut-centre de l'illustration)
    x0 = max(0, min(w - side, int(w * 0.52) - side // 2))
    y0 = max(0, min(h - side, int(h * 0.48) - side // 2))
    face = src.crop((x0, y0, x0 + side, y0 + side)).resize((big, big), Image.LANCZOS)
    out = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, big - 1, big - 1), fill=255)
    out.paste(face, (0, 0), mask)
    d = ImageDraw.Draw(out)
    rw = max(4, big // 14)
    d.ellipse((rw // 2, rw // 2, big - 1 - rw // 2, big - 1 - rw // 2), outline=order_color(order), width=rw)
    if order > 0:
        cs = int(big * 0.42)
        cx0 = big - cs
        d.ellipse((cx0, cx0, big - 1, big - 1), fill=order_color(order), outline="white", width=max(3, big // 36))
        try:
            fnt = ImageFont.truetype("segoeuib.ttf", int(cs * 0.6))
        except OSError:
            fnt = ImageFont.load_default()
        d.text((cx0 + cs / 2, cx0 + cs / 2), str(order), font=fnt, fill="white", anchor="mm")
    return out.resize((size, size), Image.LANCZOS)


def class_avatar(klass, size=44, order=0):
    """CTkImage de l'avatar (source 2x pour rester net en HiDPI), ou None si classe inconnue."""
    key = (class_id(klass), size, order)
    if key[0] is None:
        return None
    if key not in _avatar_cache:
        img = class_avatar_pil(klass, size * 2, order)
        if img is None:
            return None
        _avatar_cache[key] = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
    return _avatar_cache[key]


# ============================================================
# ICÔNE (générée : plus de dépendance à un fichier externe)
# ============================================================
def make_app_icon(size=256):
    s = 4  # suréchantillonnage pour un anti-crénelage propre
    big = size * s
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    top, bot = (138, 108, 255), (94, 62, 220)
    for y in range(big):
        t = y / big
        col = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)) + (255,)
        d.line([(0, y), (big, y)], fill=col)
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, big - 1, big - 1], radius=int(big * 0.24), fill=255)
    img.putalpha(mask)
    try:
        fnt = ImageFont.truetype("segoeuib.ttf", int(big * 0.62))
    except OSError:
        fnt = ImageFont.load_default()
    d = ImageDraw.Draw(img)
    bbox = d.textbbox((0, 0), "D", font=fnt)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((big - w) / 2 - bbox[0], (big - h) / 2 - bbox[1]), "D", font=fnt, fill="white")
    return img.resize((size, size), Image.LANCZOS)


# ============================================================
# OUTILS FENÊTRES FLOTTANTES
# ============================================================
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


# ============================================================
# OVERLAY DE CHANGEMENT DE FENÊTRE
# ============================================================
class SwitchOverlay:
    """HUD « Perso N · Nom · Classe » affiché en haut, centré sur l'écran du perso."""

    def __init__(self, root):
        self.root = root
        self.win = None
        self._hide_job = None
        self._fade_job = None

    def _build(self):
        w = tk.Toplevel(self.root)
        w.withdraw()
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        self.win = w
        self.outer = tk.Frame(w, bd=0, highlightthickness=2)
        self.outer.pack()
        self.inner = tk.Frame(self.outer, bd=0)
        self.inner.pack(padx=20, pady=14)
        self.badge = tk.Canvas(self.inner, width=46, height=46, highlightthickness=0, bd=0)
        self.badge.pack(side="left", padx=(0, 14))
        txt = tk.Frame(self.inner, bd=0)
        txt.pack(side="left")
        self.txt = txt
        self.name_lbl = tk.Label(txt, font=F(17, "bold"), anchor="w", bd=0)
        self.name_lbl.pack(anchor="w")
        self.sub_lbl = tk.Label(txt, font=F(10), anchor="w", bd=0)
        self.sub_lbl.pack(anchor="w")
        self.dots = tk.Canvas(txt, height=10, highlightthickness=0, bd=0)
        self.dots.pack(anchor="w", pady=(6, 0))
        make_click_through(w)

    def show(self, order, hwnd, title, total=0):
        if self.win is None or not self.win.winfo_exists():
            self._build()
        for job in (self._hide_job, self._fade_job):
            if job:
                self.root.after_cancel(job)
        bg, fg, dim = resolve(CARD), resolve(TEXT), resolve(TEXT_DIM)
        name, klass = core.split_title(title)
        color = order_color(order)

        for wdg in (self.win, self.inner, self.txt, self.name_lbl, self.sub_lbl,
                    self.badge, self.dots):
            wdg.configure(bg=bg)
        self.outer.configure(bg=bg, highlightbackground=color, highlightcolor=color)
        self.name_lbl.configure(text=name, fg=fg)
        sub = f"Personnage {order}" if order else "Personnage"
        if klass:
            sub += f"  ·  {klass}"
        self.sub_lbl.configure(text=sub, fg=dim)

        self.badge.delete("all")
        av = class_avatar_pil(klass, 58, order)
        if av is not None:
            self._badge_img = ImageTk.PhotoImage(av)  # référence gardée (sinon image vide)
            self.badge.configure(width=58, height=58)
            self.badge.create_image(29, 29, image=self._badge_img)
        else:
            self.badge.configure(width=46, height=46)
            self.badge.create_oval(2, 2, 44, 44, fill=color, outline=color)
            self.badge.create_text(23, 23, text=str(order) if order else "•",
                                   fill="white", font=F(17, "bold"))

        self.dots.delete("all")
        if total > 1:
            self.dots.configure(width=total * 14)
            for i in range(total):
                c = order_color(i + 1) if i + 1 == order else resolve(BORDER)
                self.dots.create_oval(i * 14 + 1, 1, i * 14 + 9, 9, fill=c, outline=c)
        else:
            self.dots.configure(width=1)

        self.win.attributes("-alpha", 0.96)
        self.win.update_idletasks()
        w = self.win.winfo_reqwidth()
        mon = core.get_monitor_rect(hwnd) if hwnd else None
        if mon:
            x, y = mon[0] + (mon[2] - mon[0] - w) // 2, mon[1] + 24
        else:
            x, y = (self.win.winfo_screenwidth() - w) // 2, 24
        self.win.geometry(f"+{x}+{y}")
        self.win.deiconify()
        self.win.lift()
        self._hide_job = self.root.after(max(300, int(core.config.overlay_ms)), self._fade)

    def _fade(self, alpha=0.96):
        self._hide_job = None
        if not self.win or not self.win.winfo_exists():
            return
        alpha -= 0.16
        if alpha <= 0:
            self.win.withdraw()
            self._fade_job = None
            return
        self.win.attributes("-alpha", alpha)
        self._fade_job = self.root.after(25, lambda: self._fade(alpha))


# ============================================================
# TOASTS (notifications non bloquantes, empilées en bas à droite)
# ============================================================
class Toaster:
    def __init__(self, root):
        self.root = root
        self.active = []

    def show(self, text, kind="info", ms=2400):
        if not core.config.show_notifs and kind == "info":
            return
        if not self.root.winfo_viewable():  # manager caché : pas de toast par-dessus le jeu
            return
        color = {"info": ACCENT, "success": SUCCESS, "warning": WARNING, "error": DANGER}[kind]
        t = tk.Toplevel(self.root)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        bg = resolve(CARD)
        t.configure(bg=color)
        body = tk.Frame(t, bg=bg)
        body.pack(padx=(4, 0), fill="both")
        tk.Label(body, text=text, bg=bg, fg=resolve(TEXT), font=F(10, "bold"),
                 padx=16, pady=11, justify="left", wraplength=360).pack()
        make_click_through(t)
        self.active.append(t)
        self._layout()
        self.root.after(ms, lambda: self._close(t))

    def _close(self, t):
        if t in self.active:
            self.active.remove(t)
        try:
            t.destroy()
        except tk.TclError:
            pass
        self._layout()

    def _layout(self):
        try:
            self.root.update_idletasks()
            right = self.root.winfo_rootx() + self.root.winfo_width() - 24
            y = self.root.winfo_rooty() + self.root.winfo_height() - 24
            for t in reversed(self.active):
                t.update_idletasks()
                y -= t.winfo_reqheight()
                t.geometry(f"+{right - t.winfo_reqwidth()}+{y}")
                y -= 8
        except tk.TclError:
            pass


# ============================================================
# CAPTURE D'UNE COMBINAISON DE TOUCHES
# ============================================================
class KeyCaptureDialog(ctk.CTkToplevel):
    """Appuyez sur une touche (avec Ctrl/Alt/Shift éventuels). Échap annule."""

    def __init__(self, parent, title, callback, allow_clear=True):
        super().__init__(parent)
        self.callback = callback
        self.title(title)
        self.geometry("420x220")
        self.resizable(False, False)
        self.configure(fg_color=BG)
        self.transient(parent.winfo_toplevel())

        ctk.CTkLabel(self, text=title, font=F(15, "bold"), text_color=TEXT).pack(pady=(26, 4))
        ctk.CTkLabel(self, text="Appuyez sur la touche ou la combinaison souhaitée",
                     font=F(11), text_color=TEXT_DIM).pack()
        self.preview = ctk.CTkLabel(self, text="…", font=F(20, "bold"), text_color=ACCENT,
                                    fg_color=ACCENT_SOFT, corner_radius=10, width=220, height=48)
        self.preview.pack(pady=16)
        hint = "Échap : annuler" + ("   ·   Retour arrière : effacer" if allow_clear else "")
        ctk.CTkLabel(self, text=hint, font=F(10), text_color=TEXT_FAINT).pack()

        self.allow_clear = allow_clear
        self.bind("<KeyPress>", self._on_key)
        self.after(80, self._grab)

    def _grab(self):
        try:
            self.lift()
            self.focus_force()
            self.grab_set()
        except tk.TclError:
            pass

    def _on_key(self, event):
        if event.keysym == "Escape":
            self.destroy()
            return
        if event.keysym == "BackSpace" and self.allow_clear and not (event.state & 0x0004):
            self.destroy()
            self.callback(None)
            return
        combo = core.event_to_combo(event)
        if combo is None:
            return
        self.preview.configure(text=core.combo_name(*combo))
        self.after(180, lambda: (self.destroy(), self.callback(combo)))
        self.unbind("<KeyPress>")
