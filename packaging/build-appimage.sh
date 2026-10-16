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
    -n Cherminal cherminal )
mv "$work"/Cherminal*.AppImage "dist/Cherminal-$version-x86_64.AppImage"
echo "Built dist/Cherminal-$version-x86_64.AppImage"
