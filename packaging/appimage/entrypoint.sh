#! /bin/bash
# `cherminal-keycapture` as the first argument runs the key capture tool.
if [ "$1" = "keycapture" ] || [ "$1" = "cherminal-keycapture" ]; then
    shift
    exec {{ python-executable }} -I -m cherminal.tools.keycapture "$@"
fi
exec {{ python-executable }} -I -m cherminal "$@"
