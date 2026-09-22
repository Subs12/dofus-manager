# -*- coding: utf-8 -*-
"""Numéro de version de Dofus Manager — source unique : APP_VERSION dans dm_core.py.

Tout le reste (fichier de version de l'exe Windows, Info.plist du .app, noms des fichiers
de la release, tag git) en est dérivé : les versions Windows et macOS ne peuvent pas diverger.

    python tools/version.py                    affiche la version (ex. 4.7)
    python tools/version.py --win              version sur 4 nombres pour Windows (4.7.0.0)
    python tools/version.py --check v4.7       échoue si le tag ne correspond pas à la version
    python tools/version.py --set 4.7          change la version dans dm_core.py
    python tools/version.py --win-file OUT     génère le fichier de version PyInstaller (exe)
"""
import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORE = ROOT / "dm_core.py"
_LINE = re.compile(r'^APP_VERSION\s*=\s*"([^"]*)"', re.M)
_FORMAT = re.compile(r"^\d+(\.\d+){1,3}$")


def get():
    m = _LINE.search(CORE.read_text(encoding="utf-8"))
    if not m:
        sys.exit("APP_VERSION introuvable dans dm_core.py")
    return m.group(1)


def validate(version):
    if not _FORMAT.match(version):
        sys.exit(f"Version invalide « {version} » : attendu 4.7, 4.7.1…")
    return version


def win_tuple(version):
    parts = [int(x) for x in validate(version).split(".")]
    return tuple(parts + [0] * (4 - len(parts)))


def set_version(version):
    validate(version)
    text = CORE.read_text(encoding="utf-8")
    CORE.write_text(_LINE.sub(f'APP_VERSION = "{version}"', text, count=1), encoding="utf-8")


def win_version_file(version):
    t = win_tuple(version)
    dotted = ".".join(map(str, t))
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={t},
    prodvers={t},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040C04B0', [
        StringStruct('CompanyName', 'Subs12'),
        StringStruct('FileDescription', 'Dofus Manager - gestionnaire de fenêtres multi-comptes'),
        StringStruct('FileVersion', '{dotted}'),
        StringStruct('InternalName', 'DofusManager'),
        StringStruct('LegalCopyright', '© 2026 Subs12. Tous droits réservés.'),
        StringStruct('OriginalFilename', 'DofusManager.exe'),
        StringStruct('ProductName', 'Dofus Manager'),
        StringStruct('ProductVersion', '{dotted}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1036, 1200])])
  ]
)
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--win", action="store_true")
    g.add_argument("--check", metavar="TAG")
    g.add_argument("--set", metavar="VERSION")
    g.add_argument("--win-file", metavar="OUT")
    a = ap.parse_args()
    if a.set:
        set_version(a.set)
        print(get())
    elif a.check:
        version = validate(get())
        if a.check.removeprefix("v") != version:
            sys.exit(f"Le tag {a.check} ne correspond pas à APP_VERSION = {version} (dm_core.py)")
        print(f"OK : {a.check} = {version}")
    elif a.win_file:
        pathlib.Path(a.win_file).write_text(win_version_file(get()), encoding="utf-8")
    elif a.win:
        print(".".join(map(str, win_tuple(get()))))
    else:
        print(validate(get()))


if __name__ == "__main__":
    main()
