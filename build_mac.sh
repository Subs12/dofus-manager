#!/bin/bash
# Dofus Manager — compilation macOS : dist/DofusManager-<version>-macos.dmg
# (glisser-déposer dans Applications ; c'est aussi le fichier de mise à jour automatique).
#   ./build_mac.sh                 (PYTHON=python3.14 ./build_mac.sh pour un autre interpréteur)
# La version vient de APP_VERSION (dm_core.py), via tools/version.py : jamais saisie ici.
# Prérequis : Python 3 de python.org (Tk inclus). Le venv .venv est créé au besoin.
set -euo pipefail
cd "$(dirname "$0")"

APP="Dofus Manager"
VERSION=$(python3 tools/version.py)
DMG="dist/DofusManager-$VERSION-macos.dmg"
# Compilation hors du Bureau : iCloud/Finder y ajoutent des attributs étendus que codesign refuse.
WORK=$(mktemp -d /tmp/dofusmanager_build.XXXXXX)
trap 'rm -rf "$WORK"' EXIT

if [ ! -x .venv/bin/python ]; then
    "${PYTHON:-python3}" -m venv .venv
fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements-mac.txt

# Icône .icns générée depuis make_app_icon (comme l'.ico sous Windows)
mkdir -p "$WORK/icon.iconset"
.venv/bin/python -c "
import sys
from dm_widgets import make_app_icon
d = sys.argv[1]
for s in (16, 32, 128, 256, 512):
    make_app_icon(s).save(f'{d}/icon_{s}x{s}.png')
    make_app_icon(s * 2).save(f'{d}/icon_{s}x{s}@2x.png')
" "$WORK/icon.iconset"
iconutil -c icns "$WORK/icon.iconset" -o "$WORK/icon.icns"

.venv/bin/python -m PyInstaller --noconfirm --windowed --name "$APP" \
    --distpath "$WORK/dist" --workpath "$WORK/pyi" --specpath "$WORK" \
    --icon "$WORK/icon.icns" \
    --osx-bundle-identifier com.subs12.dofusmanager \
    --add-data "$PWD/assets/classes:assets/classes" \
    --collect-data customtkinter \
    --hidden-import pystray._darwin --hidden-import PIL._tkinter_finder \
    --exclude-module dm_win \
    dofus_manager.py

BUNDLE="$WORK/dist/$APP.app"
PLIST="$BUNDLE/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleVersion string $VERSION" "$PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Set :CFBundleVersion $VERSION" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :NSHumanReadableCopyright string © 2026 Subs12" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :LSMinimumSystemVersion string 11.0" "$PLIST" 2>/dev/null || true
# Signature ad hoc (aucun certificat requis) : obligatoire sur Apple Silicon après modif du plist.
xattr -cr "$BUNDLE"
codesign --force --deep --sign - "$BUNDLE"
codesign --verify --deep --strict "$BUNDLE"

# Contrôle : la version inscrite dans le .app doit être celle de dm_core.py.
ACTUAL=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$PLIST")
if [ "$ACTUAL" != "$VERSION" ]; then
    echo "Version du .app ($ACTUAL) différente de APP_VERSION ($VERSION)" >&2
    exit 1
fi

mkdir -p dist
rm -f "$DMG"

# DMG : l'app + un raccourci vers Applications
mkdir -p "$WORK/dmg"
ditto "$BUNDLE" "$WORK/dmg/$APP.app"
ln -s /Applications "$WORK/dmg/Applications"
# hdiutil échoue parfois (« Resource busy ») sur les machines de CI : quelques essais.
for attempt in 1 2 3 4 5; do
    hdiutil create -volname "$APP $VERSION" -srcfolder "$WORK/dmg" -ov -format UDZO "$DMG" >/dev/null && break
    [ "$attempt" = 5 ] && exit 1
    sleep 5
done

# Pas de .app dans dist/ : si le dossier est synchronisé par iCloud (Bureau, Documents), les
# attributs étendus ajoutés cassent la signature et macOS refuse l'autorisation Accessibilité.
# L'app s'installe depuis le DMG, dans /Applications.
echo "OK : $DMG (version $ACTUAL)"
