#!/usr/bin/env bash
# Remove what Cherminal never uses from a bundled app folder (the AppImage's
# AppDir, or the unpacked AppImage in the eLux package):
#
#   packaging/slim-appdir.sh [--x11-only] APPDIR
#
# The PyQt6 wheel carries all of Qt (QML, Quick 3D, Multimedia with its own
# FFmpeg, WebSockets, ...), about 270 MB, and Python carries its test suite
# and Tk. Cherminal needs QtCore, QtGui, QtWidgets and QtPrintSupport, so this
# keeps those bindings, the plugins a desktop needs, and exactly the Qt
# libraries they link to (followed through each file's DT_NEEDED entries),
# and deletes the rest. --x11-only also drops Wayland, for eLux.
#
# Running it twice does nothing more, so it is safe on an AppDir that has
# already been slimmed.
set -euo pipefail
x11_only=false
if [ "${1:-}" = "--x11-only" ]; then x11_only=true; shift; fi
appdir=${1:?usage: slim-appdir.sh [--x11-only] APPDIR}
before=$(du -sm "$appdir" | cut -f1)

pyqt=$(find "$appdir" -type d -path '*/site-packages/PyQt6' | head -1)
[ -n "$pyqt" ] || { echo "No PyQt6 in $appdir" >&2; exit 1; }
qt="$pyqt/Qt6"

# Python bindings: only the modules Cherminal imports (and sip, which they use).
keep_bindings="QtCore QtGui QtWidgets QtPrintSupport"
for mod in "$pyqt"/Qt*.abi3.so; do
    name=$(basename "$mod" .abi3.so)
    [[ " $keep_bindings " == *" $name "* ]] || rm -f "$mod"
done
rm -rf "$pyqt"/*.pyi "$pyqt/bindings" "$pyqt/uic" "$pyqt/lupdate" \
       "$qt/qml" "$qt/qsci" "$qt/translations" "$qt/libexec" "$qt/resources"

# Plugins: the window systems, desktop themes and input methods (compose keys,
# IBus), image formats, icon themes and printing. Everything else is for Qt
# modules Cherminal doesn't load.
keep_plugins="platforms platformthemes platforminputcontexts xcbglintegrations
              imageformats iconengines printsupport
              wayland-decoration-client wayland-graphics-integration-client
              wayland-shell-integration"
for dir in "$qt"/plugins/*/; do
    name=$(basename "$dir")
    [[ " $(echo $keep_plugins) " == *" $name "* ]] || rm -rf "$dir"
done
# Of the platforms, the X11 and Wayland desktops, and the off-screen ones that
# tests and headless runs use (not framebuffers, EGL consoles or VNC).
find "$qt/plugins/platforms" -name '*.so' \
    ! -name libqxcb.so ! -name 'libqwayland*.so' \
    ! -name libqoffscreen.so ! -name libqminimal.so -delete
rm -f "$qt/plugins/imageformats/libqpdf.so"         # would pull in Qt PDF
if $x11_only; then
    rm -rf "$qt"/plugins/wayland-*
    find "$qt/plugins/platforms" -name 'libqwayland*.so' -delete
fi

# Qt's libraries: keep the ones the remaining bindings and plugins need,
# directly or through each other.
needed() { readelf -d "$1" 2>/dev/null | sed -n 's/.*(NEEDED).*\[\(.*\)\]/\1/p'; }
declare -A keep=()
queue=("$pyqt"/*.so)
mapfile -t -O "${#queue[@]}" queue < <(find "$qt/plugins" -name '*.so')
while [ "${#queue[@]}" -gt 0 ]; do
    file=${queue[0]}
    queue=("${queue[@]:1}")
    for lib in $(needed "$file"); do
        if [ -e "$qt/lib/$lib" ] && [ -z "${keep[$lib]:-}" ]; then
            keep[$lib]=1
            queue+=("$qt/lib/$lib")
        fi
    done
done
for lib in "$qt"/lib/*; do
    name=$(basename "$lib")
    [ -n "${keep[$name]:-}" ] && continue
    # A symlink stays if it points at a library that stays.
    [ -L "$lib" ] && [ -n "${keep[$(basename "$(readlink "$lib")")]:-}" ] && continue
    rm -rf "$lib"
done
# Every Qt library something still asks for must still be there.
missing=$(for f in "$pyqt"/*.so $(find "$qt/plugins" "$qt/lib" -name '*.so*' -type f); do
              needed "$f"; done | sort -u | grep '^libQt6' |
          while read -r lib; do [ -e "$qt/lib/$lib" ] || echo "$lib"; done)
[ -z "$missing" ] || { echo "slim-appdir: removed Qt libraries still needed: $missing" >&2; exit 1; }

# Python: its tests, Tk, IDLE, the C headers and static library for building
# extensions, and the installers, none of which run in Cherminal.
for stdlib in $(find "$appdir" -type d -regex '.*/lib/python3\.[0-9]+' ! -path '*/site-packages/*'); do
    rm -rf "$stdlib"/test "$stdlib"/idlelib "$stdlib"/tkinter "$stdlib"/turtledemo \
           "$stdlib"/ensurepip "$stdlib"/lib2to3 "$stdlib"/config-3* \
           "$stdlib"/lib-dynload/_tkinter* "$stdlib"/lib-dynload/_test* \
           "$stdlib"/site-packages/pip "$stdlib"/site-packages/pip-* \
           "$stdlib"/site-packages/setuptools "$stdlib"/site-packages/setuptools-* \
           "$stdlib"/site-packages/_distutils_hack "$stdlib"/site-packages/wheel \
           "$stdlib"/site-packages/wheel-*
done
find "$appdir" -depth -type d \( -name tcltk -o -name tcl8\* -o -name tk8\* \) \
    ! -path '*/site-packages/*' -exec rm -rf {} +
find "$appdir" -type d -path '*/include/python3*' -prune -exec rm -rf {} +

after=$(du -sm "$appdir" | cut -f1)
echo "Slimmed $appdir from ${before} MB to ${after} MB"
