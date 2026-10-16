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
  xterm (256/true colour), Wyse 50, Wyse 60, TeleVideo 925/950, ADM-3A,
  and IBM 3278/3279 models 2-5 for mainframes (TN3270).
- **Connections:** SSH (keys, agent, password, host-key verification),
  Telnet (TTYPE, NAWS, binary, echo/SGA, optional TLS), TN3270, serial
  ports, local shell.
- **Key mapping:** per-emulation defaults, reusable keymap files with
  inheritance, per-session overrides, application cursor/keypad aware, a
  press-to-capture editor, and `action:` bindings (paste, break, macros).
- **Saved sessions:** one readable TOML file per session under
  `~/.config/cherminal/sessions/`; no passwords are stored.
- **Scale to window:** by default the text grows and shrinks with the window
  while the host keeps its fixed grid (80×24 etc.); switch a session to
  "add rows and columns" instead, or toggle View › Scale text to window.
- **Function-key bar** built from each session's macros, tabs, scrollback,
  copy/paste (including X11 primary selection), colour schemes, any code page.
- **`cherminal-keycapture`:** records exactly what another emulator sends for
  each key, over Telnet, and saves it as a Cherminal keymap. This is how to
  carry an existing TinyTerm keyboard setup across.

## Install and run

### On a workstation with no internet (AppImage)

Download `Cherminal-<version>-x86_64.AppImage` from a release (or the
`appimage` workflow's artifact), copy it over, and run it:

```sh
chmod +x Cherminal-0.2.0-x86_64.AppImage
./Cherminal-0.2.0-x86_64.AppImage                 # same options as `cherminal`
./Cherminal-0.2.0-x86_64.AppImage keycapture --name mykeys
```

It carries its own Python and Qt and runs on x86_64 distributions from
about 2019 onward (glibc 2.28+: RHEL/Rocky 8, Debian 10, Ubuntu 20.04).
If it reports a FUSE error, install `libfuse2` (or `fuse-libs`), or run it
with `--appimage-extract-and-run`. Build one yourself with
`packaging/build-appimage.sh`.

### Updating

Run `cherminal --version` to see what you have (see
[CHANGELOG.md](CHANGELOG.md) for what changed). For an AppImage, replace the
file with the new one. For a pip install, from an updated checkout:

```sh
git pull
pip install --upgrade .
```

### With pip

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

## IBM mainframes (TN3270)

Choose connection **telnet** and emulation `ibm3278-2` (24×80), `ibm3278-3`
(32×80), `ibm3278-4` (43×80) or `ibm3278-5` (27×132); the larger models
switch to their size when the host asks. Tick **Use TLS** for port 992 or
any secure TN3270 port; untick "Check the host's certificate" only if the
host uses a certificate from an in-house CA that this machine doesn't
trust. The character set defaults to EBCDIC code page 037 (US/Canada); set
e.g. `cp500`, `cp273` or `cp1140` under Terminal › Character set if your
host uses another.

Typing edits the screen locally and the attention keys send it. The
default keyboard (built-in keymap `ibm3270`):

| Key | 3270 key | Key | 3270 key |
|---|---|---|---|
| Enter | Enter | Shift+Enter | New line |
| F1-F12 | PF1-PF12 | Shift+F1-F12 | PF13-PF24 |
| PageUp / PageDown | PF7 / PF8 | Alt+F1/F2/F3 | PA1/PA2/PA3 |
| Pause | Clear | Escape | Reset (unlock keyboard) |
| Tab / Shift+Tab | Next / previous field | Home | First input field |
| End | End of field | Insert | Insert mode |
| Backspace | Erase left | Delete | Delete |
| Ctrl+End | Erase to end of field | Ctrl+Delete | Erase all input |

Any key can be remapped with `action:` and one of `enter`, `clear`,
`pf1`-`pf24`, `pa1`-`pa3`, `reset`, `tab`, `backtab`, `home`, `newline`,
`up`, `down`, `left`, `right`, `field-end`, `insert`, `erase`, `delete`,
`erase-eof`, `erase-input`. Put overrides in the session's key overrides or
in a keymap file with `inherit = "ibm3270"`, for example
`Ctrl+Enter = "action:enter"`. A keymap file shared as described below gives
every machine the same mainframe keyboard.

The status bar shows the 3270 operator information: `X System` while the
host has the keyboard locked, `X Protected` when typing outside an input
field, `Insert`, and the cursor's row/column.

Not yet supported: TN3270E (LU names, SysReq/Attn), 3287 printing, file
transfer (IND$FILE), and 5250 (IBM i).

## Limited mode for shared workstations

```sh
./Cherminal-x86_64.AppImage --limited "Mainframe A" "Mainframe B"
```

`--limited` opens the named sessions with a File menu offering only
**Close tab** and **Exit**. Users can't open the session list, create or
edit sessions, use Quick connect or start a local shell, and those menu
shortcuts are gone too. Edit, View, Session and Help stay. Started with no
session names, it shows a list of the available sessions with only a
Connect button (local shell sessions are left out).

Put the command in the launcher or desktop icon the users start, for
example together with a shared setup folder below.

## Sharing sessions across machines

A session file (`.cherminal`) holds one or more connections together with
every custom keymap they use, so the key mappings always travel with them.

Set the connections up once on any machine, then export them:

```sh
cherminal --export mainframes.cherminal "Mainframe A" "Mainframe B"
```

(or select them in File › Sessions and press Export…). There are two ways
to use the file on other machines.

**Shared setup (recommended for many thin clients).** Put the file in a
folder Cherminal reads at start-up. Every client then sees the same
sessions, marked `[shared]`, and an update to the file reaches all of them
the next time the Sessions window opens. Nothing needs to be imported, so
it also works where the home folder is wiped at logoff. Cherminal looks in,
first match wins:

1. each folder in `$CHERMINAL_SITE_DIR` (`:`-separated), for example a
   mounted network share;
2. `cherminal-config/` next to the AppImage;
3. `/etc/xdg/cherminal/` (each `$XDG_CONFIG_DIRS` folder).

Each of these may hold `*.cherminal` files and `sessions/` and `keymaps/`
folders laid out like `~/.config/cherminal`. If a user edits a shared
session, their copy is saved in their own folder and shown as
`[shared, edited here]`; deleting it goes back to the shared version.

**Import.** `cherminal --import mainframes.cherminal` (or Import… in the
Sessions window) copies the sessions and keymaps into the user's own
folder, replacing any with the same names.

## Development

```sh
pip install -e '.[dev]'
pytest
```

The emulation, keymap, config and Telnet code is pure Python and tested
headlessly; only `cherminal/gui` imports Qt.
