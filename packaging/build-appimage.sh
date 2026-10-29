#!/usr/bin/env bash
# Build dist/Cherminal-<version>-x86_64.AppImage: one file with its own
# Python and Qt, for workstations without pip or internet access.
#
# Needs network access *at build time* (PyPI and the python-appimage base
# image); the resulting AppImage needs nothing.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
LINUX_TAG="${LINUX_TAG:-manylinux_2_28_x86_64}"

version=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' cherminal/__init__.py)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

python3 -m pip wheel --no-deps -w "$work/wheels" . >/dev/null
wheel=$(ls "$work"/wheels/cherminal-*.whl)

recipe="$work/cherminal"
cp -r packaging/appimage "$recipe"
# Pin the app wheel plus its runtime dependencies from pyproject.toml.
{
    echo "$wheel"
    python3 - <<'PY'
import tomllib
for dep in tomllib.load(open("pyproject.toml", "rb"))["project"]["dependencies"]:
    print(dep)
PY
} > "$recipe/requirements.txt"

python3 -m pip show python-appimage >/dev/null 2>&1 || python3 -m pip install python-appimage
mkdir -p dist
( cd "$work" && python3 -m python_appimage build app -l "$LINUX_TAG" -p "$PYTHON_VERSION" \
    -n Cherminal --no-packaging cherminal )
appdir="$work/Cherminal-x86_64"

# Qt's X11 plugin (libqxcb) needs xcb-util libraries that the PyQt6 wheel
# leaves out and many desktops don't install ("xcb-cursor0 or libxcb-cursor0
# is needed to load the Qt xcb platform plugin"). Bundle them next to Qt's
# own libraries, where the plugin's RUNPATH finds them, without touching
# LD_LIBRARY_PATH (which would leak into local shells). They come from Ubuntu
# 20.04, which is old enough for every glibc the manylinux_2_28 Python runs on.
# libxkbcommon-x11 crashes against a different libxkbcommon, so the matching
# libxkbcommon comes too and Qt uses that pair rather than the system's.
UBUNTU=https://archive.ubuntu.com/ubuntu/pool
XCB_DEBS="
main/x/xcb-util/libxcb-util1_0.4.0-0ubuntu3_amd64.deb 83f9a455c8c6e787fcad27a84108704c7aa7669405f2af097cd25cfeeb10d82a
main/x/xcb-util-image/libxcb-image0_0.4.0-1build1_amd64.deb 4002be5159fe91fcfbc6cdb68871163dbfd5c1092341bb51f26079e25b421d92
main/x/xcb-util-keysyms/libxcb-keysyms1_0.4.0-1build1_amd64.deb 6cfbd86d2e1c66d2d8d0a6a17f27f0b825fc0d595647674714a2926a616bdae6
main/x/xcb-util-renderutil/libxcb-render-util0_0.3.9-1build1_amd64.deb 5486323b1a43b8d4d1f19986fac99a25c00676cd5596926d973e4966c8f05a84
main/x/xcb-util-wm/libxcb-icccm4_0.4.1-1.1_amd64.deb 03cf5acb68f7d6bffa378f9d30e8d519ee3e5b10340df741af8c0d8bbaf5d3d4
main/libx/libxcb/libxcb-xkb1_1.14-2_amd64.deb 300c205cf611ce1cfae89fb490c7aeec297aea0ccb82ea15d9941078a09882e3
main/libx/libxkbcommon/libxkbcommon-x11-0_0.10.0-1_amd64.deb 929d5e4ee88d6f5f3b09e238ffae60d667e4c9c4731a0210227b092fc578c6ac
main/libx/libxkbcommon/libxkbcommon0_0.10.0-1_amd64.deb b704ce1751dd938025b88a84c4054d4f36651661e473efeb3da8ed39aaf05868
universe/x/xcb-util-cursor/libxcb-cursor0_0.1.1-4ubuntu1_amd64.deb c9b5d1ad4af57397b1bd77e0a92750e34419def134c0282a0836ae9efc07cf64
"
qtlib=$(dirname "$(find "$appdir" -path '*/PyQt6/Qt6/lib/libQt6Core.so.6' | head -1)")
mkdir -p "$work/xcb"
while read -r path sum; do
    [ -n "$path" ] || continue
    deb="$work/xcb/$(basename "$path")"
    curl -fsSL --retry 3 -o "$deb" "$UBUNTU/$path"
    echo "$sum  $deb" | sha256sum -c --quiet -
    ( cd "$work/xcb" && ar x "$deb" data.tar.xz && tar -xJf data.tar.xz && rm data.tar.xz )
done <<< "$XCB_DEBS"
for lib in "$work"/xcb/usr/lib/x86_64-linux-gnu/*.so.*; do
    [ -L "$lib" ] && cp -L "$lib" "$qtlib/"     # one real file under each soname
done
# Every library the plugin needs must now come from the system's basics or Qt's folder.
plugin=$(find "$appdir" -path '*/PyQt6/Qt6/plugins/platforms/libqxcb.so')
for soname in libxcb-cursor.so.0 libxcb-util.so.1 libxcb-image.so.0 libxcb-keysyms.so.1 \
              libxcb-render-util.so.0 libxcb-icccm.so.4 libxcb-xkb.so.1 libxkbcommon-x11.so.0 \
              libxkbcommon.so.0; do
    found=$(ldd "$plugin" | awk -v l="$soname" '$1 == l {print $3}')
    [ -n "$found" ] && [ "$(dirname "$(realpath "$found")")" = "$(realpath "$qtlib")" ] \
        || { echo "$soname not bundled: ${found:-not found}" >&2; exit 1; }
done

( cd "$work" && python3 -c "from python_appimage.appimage import build_appimage
build_appimage('Cherminal-x86_64', destination='Cherminal-x86_64.AppImage')" )
mv "$work"/Cherminal-x86_64.AppImage "dist/Cherminal-$version-x86_64.AppImage"
echo "Built dist/Cherminal-$version-x86_64.AppImage"
