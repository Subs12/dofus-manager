#!/bin/bash
# Dofus Manager — compilation macOS : dist/Dofus Manager.app, puis DofusManager-<version>.dmg
# (glisser-déposer dans Applications) et DofusManager-<version>-macos.zip (asset de mise à jour).
#   ./build_mac.sh
# Prérequis : Python 3 de python.org (Tk inclus). Le venv .venv est créé au besoin.
set -euo pipefail
cd "$(dirname "$0")"

APP="Dofus Manager"
VERSION=$(sed -n 's/^APP_VERSION *= *"\(.*\)"/\1/p' dm_core.py)
# Compilation hors du Bureau : iCloud/Finder y ajoutent des attributs étendus que codesign refuse.
WORK=$(mktemp -d /tmp/dofusmanager_build.XXXXXX)
trap 'rm -rf "$WORK"' EXIT

if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
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

mkdir -p dist
rm -rf "dist/$APP.app" "dist/$APP" "dist/DofusManager-$VERSION-macos.zip" "dist/DofusManager-$VERSION.dmg"

# Archive de mise à jour (asset GitHub attendu par dm_update)
ditto -c -k --keepParent "$BUNDLE" "dist/DofusManager-$VERSION-macos.zip"

# DMG : l'app + un raccourci vers Applications
mkdir -p "$WORK/dmg"
ditto "$BUNDLE" "$WORK/dmg/$APP.app"
ln -s /Applications "$WORK/dmg/Applications"
hdiutil create -volname "$APP" -srcfolder "$WORK/dmg" -ov -format UDZO "dist/DofusManager-$VERSION.dmg" >/dev/null

# Pas de .app dans dist/ : si le dossier est synchronisé par iCloud (Bureau, Documents), les
# attributs étendus ajoutés cassent la signature et macOS refuse l'autorisation Accessibilité.
# L'app s'installe depuis le DMG, dans /Applications.
echo "OK : dist/DofusManager-$VERSION.dmg"
echo "     dist/DofusManager-$VERSION-macos.zip"
