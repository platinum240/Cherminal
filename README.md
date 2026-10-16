# Cherminal

A terminal emulator for Linux in the spirit of Century Software's TinyTerm:
for connecting to Unix hosts, line-of-business applications, network gear
and serial devices that expect a *real* terminal (VT220, SCO ANSI, Wyse 60,
TeleVideo...), with key mapping and saved sessions as first-class features.

TinyTerm's own Linux edition (TinyTERM ITX Desktop) was discontinued in 2018
and no longer runs on current distributions. Cherminal is a clean-room
replacement; see [docs/SPEC.md](docs/SPEC.md) for the feature scope, the
sources it was derived from, and the architecture.

## Features

- **Emulations:** VT100, VT220, VT320, VT420, SCO ANSI, AT386, Linux console,
  xterm (256/true colour), Wyse 50, Wyse 60, TeleVideo 925/950, ADM-3A.
- **Connections:** SSH (keys, agent, password, host-key verification),
  Telnet (TTYPE, NAWS, binary, echo/SGA), serial ports, local shell.
- **Key mapping:** per-emulation defaults, reusable keymap files with
  inheritance, per-session overrides, application cursor/keypad aware, a
  press-to-capture editor, and `action:` bindings (paste, break, macros).
- **Saved sessions:** one readable TOML file per session under
  `~/.config/cherminal/sessions/`; no passwords are stored.
- **Function-key bar** built from each session's macros, tabs, scrollback,
  copy/paste (including X11 primary selection), colour schemes, any code page.
- **`cherminal-keycapture`:** records exactly what another emulator sends for
  each key, over Telnet, and saves it as a Cherminal keymap. This is how to
  carry an existing TinyTerm keyboard setup across.

## Install and run

```sh
pip install .
cherminal                              # session manager
cherminal --ssh me@server -e vt220
cherminal --telnet 10.0.0.5 -e wyse60
cherminal --serial /dev/ttyUSB0 --baud 9600
cherminal --local
cherminal "Warehouse"                  # a saved session
```

Requires Python 3.11+, PyQt6, paramiko and pyserial. For serial ports your
user usually needs to be in the `dialout` group.

## Keymaps

Key names look like `F5`, `Shift+F1`, `Ctrl+Up`, `Keypad5`, `app:Up`
(application cursor mode only). Values use `\e` for Esc, `\r`, `\xHH`, `^A`
caret notation, or `action:paste`, `action:break`, `action:macro:NAME`.

```toml
# ~/.config/cherminal/keymaps/site.toml
inherit = "wyse"
[keys]
Delete = "\\eW"
F12 = "^AK\\r"
```

See `examples/` for a session and a keymap.

### Copying another emulator's keyboard

```sh
cherminal-keycapture --port 2323 --name tinyterm-wyse60 --inherit wyse
```

Then, from TinyTerm (or any emulator) set to the emulation you use, Telnet
to this machine on port 2323 and press each key it asks for. The keymap is
saved to `~/.config/cherminal/keymaps/tinyterm-wyse60.toml`.

## Development

```sh
pip install -e '.[dev]'
pytest
```

The emulation, keymap, config and Telnet code is pure Python and tested
headlessly; only `cherminal/gui` imports Qt.
