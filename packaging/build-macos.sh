#!/usr/bin/env bash
# Build Cherminal.app for this Mac's architecture (arm64 or x86_64) and wrap
# it as dist/Cherminal-<version>-macos-<arch>.dmg (drag to Applications) and
# .pkg (installs into /Applications; what Jamf and other MDMs deploy).
#
# Run on macOS with Python 3.11 or later and the Xcode command line tools.
# Needs network access at build time (PyPI); the app needs nothing.
#
# Signing and notarization are optional and off unless these are set
# (see docs/MACOS.md):
#   CODESIGN_IDENTITY   "Developer ID Application: Name (TEAMID)"
#   INSTALLER_IDENTITY  "Developer ID Installer: Name (TEAMID)" for the .pkg
#   NOTARY_PROFILE      a `xcrun notarytool store-credentials` profile name
set -euo pipefail
cd "$(dirname "$0")/.."
[ "$(uname)" = Darwin ] || { echo "build-macos.sh runs on macOS" >&2; exit 1; }

version=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' cherminal/__init__.py)
arch=$(uname -m)
build=build/macos
rm -rf "$build/work" "$build/dist" "$build/Cherminal.iconset"
mkdir -p "$build" dist

# A clean environment with only Cherminal's dependencies and PyInstaller.
python3 -m venv "$build/venv"
"$build/venv/bin/pip" install -q --upgrade pip
"$build/venv/bin/pip" install -q . pyinstaller

# The app icon, from the 1024 px logo.
iconset="$build/Cherminal.iconset"
mkdir -p "$iconset"
for size in 16 32 128 256 512; do
    sips -z $size $size packaging/macos/cherminal-1024.png \
        --out "$iconset/icon_${size}x${size}.png" >/dev/null
    double=$((size * 2))
    sips -z $double $double packaging/macos/cherminal-1024.png \
        --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$iconset" -o "$build/Cherminal.icns"

"$build/venv/bin/pyinstaller" --noconfirm --clean --log-level WARN \
    --distpath "$build/dist" --workpath "$build/work" packaging/macos/cherminal.spec
app="$build/dist/Cherminal.app"

if [ -n "${CODESIGN_IDENTITY:-}" ]; then
    codesign --force --deep --timestamp --options runtime \
        --entitlements packaging/macos/entitlements.plist \
        --sign "$CODESIGN_IDENTITY" "$app"
    codesign --verify --deep --strict --verbose=2 "$app"
fi

# Smoke test: the bundled interpreter starts and finds its modules.
"$app/Contents/MacOS/Cherminal" --version
XDG_CONFIG_HOME=$(mktemp -d) "$app/Contents/MacOS/Cherminal" --list
"$app/Contents/MacOS/Cherminal" keycapture --help | head -1

name="Cherminal-$version-macos-$arch"

# Disk image: the app and a link to /Applications to drag it onto.
stage="$build/dmg"
rm -rf "$stage" && mkdir -p "$stage"
cp -R "$app" "$stage/"
ln -s /Applications "$stage/Applications"
rm -f "dist/$name.dmg"
# hdiutil sometimes fails with "Resource busy" while macOS still holds the
# staged files (seen on CI runners); try again a few times before giving up.
for attempt in 1 2 3 4; do
    hdiutil create -quiet -volname "Cherminal $version" -srcfolder "$stage" \
        -fs HFS+ -format UDZO "dist/$name.dmg" && break
    [ "$attempt" = 4 ] && { echo "hdiutil create failed" >&2; exit 1; }
    echo "hdiutil create failed, trying again ($attempt)" >&2
    rm -f "dist/$name.dmg"
    sleep $((attempt * 5))
done
[ -n "${CODESIGN_IDENTITY:-}" ] && codesign --timestamp --sign "$CODESIGN_IDENTITY" "dist/$name.dmg"

# Installer package for /Applications.
pkg_sign=()
[ -n "${INSTALLER_IDENTITY:-}" ] && pkg_sign=(--sign "$INSTALLER_IDENTITY" --timestamp)
pkgbuild --quiet --component "$app" --install-location /Applications \
    --identifier io.github.platinum240.cherminal.pkg --version "$version" \
    ${pkg_sign[@]+"${pkg_sign[@]}"} "dist/$name.pkg"

if [ -n "${NOTARY_PROFILE:-}" ]; then
    notarize=("dist/$name.dmg")
    # Apple only notarizes an installer package signed with an Installer ID.
    [ -n "${INSTALLER_IDENTITY:-}" ] && notarize+=("dist/$name.pkg")
    for f in "${notarize[@]}"; do
        xcrun notarytool submit "$f" --keychain-profile "$NOTARY_PROFILE" --wait
        xcrun stapler staple "$f"
    done
fi
echo "Built dist/$name.dmg and dist/$name.pkg"
