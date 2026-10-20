#!/usr/bin/env bash
# Build Cherminal for eLux thin clients: an eLux package tree, and the
# .epm/.fpm package files when Unicon's epkg tool is installed.
#
#   packaging/elux/build-epm.sh [path/to/Cherminal-<version>-x86_64.AppImage]
#
# The package carries the unpacked AppImage in /opt/cherminal, so clients need
# no FUSE, Python or Qt. epkg comes with the eLux SDK (SDK VM); without it this
# script stops after writing dist/cherminal-elux-<version>.tar.gz, which you
# copy to the SDK VM, unpack and build there. See packaging/elux/README.md.
set -euo pipefail
cd "$(dirname "$0")/../.."
here=packaging/elux
version=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' cherminal/__init__.py)
appimage=$(realpath "${1:-dist/Cherminal-$version-x86_64.AppImage}")
if [ ! -f "$appimage" ]; then
    echo "No AppImage at $appimage; build one with packaging/build-appimage.sh" >&2
    exit 1
fi

tree="dist/cherminal-elux-$version"
fpm="$tree/input/cherminal"
rm -rf "$tree"
mkdir -p "$fpm/opt" "$tree/elux"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
( cd "$work" && "$appimage" --appimage-extract >/dev/null )
mv "$work/squashfs-root" "$fpm/opt/cherminal"

# Commands on the PATH, and the menu entry with its icons.
mkdir -p "$fpm/usr/bin"
printf '#!/bin/sh\nexec /opt/cherminal/AppRun "$@"\n' > "$fpm/usr/bin/cherminal"
printf '#!/bin/sh\nexec /opt/cherminal/AppRun keycapture "$@"\n' \
    > "$fpm/usr/bin/cherminal-keycapture"
chmod 755 "$fpm/usr/bin/cherminal" "$fpm/usr/bin/cherminal-keycapture"
install -D -m 644 packaging/appimage/cherminal.desktop \
    "$fpm/usr/share/applications/cherminal.desktop"
for png in cherminal/resources/cherminal-[0-9]*.png; do
    size=$(basename "$png" .png | sed 's/cherminal-//')
    install -D -m 644 "$png" "$fpm/usr/share/icons/hicolor/${size}x${size}/apps/cherminal.png"
done
install -D -m 644 cherminal/resources/cherminal.svg \
    "$fpm/usr/share/icons/hicolor/scalable/apps/cherminal.svg"
install -D -m 644 "$here/policy.toml.example" "$fpm/etc/cherminal/policy.toml.example"
install -D -m 644 LICENSE "$fpm/usr/share/doc/cherminal/LICENSE"

# The site policy, when there is one, goes in a second package part so it can
# be updated (or left out) without reinstalling the application.
fill() { sed -e "s/@VERSION@/$version/g" "$1"; }
fill "$here/ebkepm.in" > "$tree/input/ebkepm"
if [ -f "$here/site/policy.toml" ]; then
    python3 -m cherminal --check-policy "$here/site/policy.toml" >/dev/null
    install -D -m 644 "$here/site/policy.toml" "$tree/input/cherminal-policy/etc/cherminal/policy.toml"
    fill "$here/ebkepm-policy.in" >> "$tree/input/ebkepm"
    echo "Including the site policy from $here/site/policy.toml"
fi
cp "$here/control" "$tree/elux/control"

if command -v epkg >/dev/null; then
    ( cd "$tree" && epkg Build --container elux7 --releaseType "${RELEASE_TYPE:-test}" )
    echo "Built the eLux package in $tree/output/container/"
else
    tar -C dist -czf "dist/cherminal-elux-$version.tar.gz" "cherminal-elux-$version"
    echo "epkg not found: wrote the package tree to dist/cherminal-elux-$version.tar.gz."
    echo "Unpack it in the eLux SDK VM and run:  epkg Build --container elux7 --releaseType test"
fi
