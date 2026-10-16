# Cherminal specification

Cherminal is a Linux terminal emulator for connecting to host systems
(Unix servers, legacy line-of-business apps, network gear, serial devices)
in the spirit of Century Software's TinyTerm. Linux has many good *xterm*
terminals, but few that emulate the terminals legacy host applications were
written for, and none that make per-host key mapping and saved connection
profiles a first-class feature. That gap is what Cherminal fills.

## How this spec was derived (clean room)

Century Software shipped a Linux edition, TinyTERM ITX Desktop, which was
discontinued in November 2018 and no longer runs on current distributions.
Its public product page and FAQ are the main reference for what users
expect: SSH (host key and password auth, RSA/DSA keys), Telnet and local
shell; 21 emulations (VT100/220/320/420 and 7-bit variants, ANSI 3.64,
SCOANSI, AT386, Linux console, xterm, Wyse 50/60/60-25, TeleVideo
912/925/950, ADM-1, IBM 3101/3151, TTY); xterm-style resizing with the
choice of growing the grid or scaling the font; selectable colours; 25+
code pages with line drawing; several saved connection profiles; a
programmable keyboard (`keyboard.dat`) and an on-screen function-key bar.

The feature set below comes only from public product documentation, general
knowledge of what this class of product does, and published terminal
standards (DEC VT100/VT220 manuals, ECMA-48, Wyse 50/60 programmer guides,
RFC 854/857/858/1073/1091 for Telnet). No TinyTerm binaries were
decompiled, disassembled or inspected, and no proprietary code, file
formats, artwork or text are reused. Cherminal's file formats are its own
(TOML), and it does not attempt to read TinyTerm's session files.

Where a behaviour is not pinned down by a public reference, the code marks
it `UNVERIFIED` so it can be checked against real hardware or a manual.

## Feature scope

| Area | Target | Status in this PR |
|---|---|---|
| Emulations | VT100, VT220, VT320, VT420, ANSI (SCO console), AT386, Linux console, xterm, Wyse 50, Wyse 60, TVI 925/950, ADM-3A | All present; VT/ANSI family is the most complete, TVI/ADM share the Wyse core |
| Emulations, later | IBM 3101/3151, TVI 912, TTY, VT 7-bit variants | Later phase |
| Code pages | Any Python codec (CP437, CP1251, CP1252, ISO 8859-x, ...) plus UTF-8, which ITX lacked | Done |
| Resize | Grow the grid (sends NAWS / SSH window change) or keep the grid and scale the font | Grid growth done; font scaling later |
| Function-key bar | Clickable buttons bound to macros | Done (toolbar from profile macros) |
| Connections | SSH, Telnet, serial, local shell | All four |
| Key mapping | Per-emulation defaults, user keymap files, per-session overrides, mode-aware keys (cursor/keypad application mode), actions and macros | Done, with a GUI capture editor |
| Saved configs | Named session profiles, one TOML file each, under `$XDG_CONFIG_HOME/cherminal` | Done |
| UI | Tabbed sessions, session manager, quick connect, copy/paste, scrollback, colours | Done (PyQt6) |
| Telnet options | BINARY, ECHO, SGA, TTYPE, NAWS | Done |
| Macros | Named byte strings bound to keys or a menu | Done |
| File transfer | XMODEM, YMODEM, ZMODEM, Kermit | Later phase |
| Printing | Transparent / pass-through print (`CSI 5i`/`CSI 4i`, Wyse `ESC d#`) to a file or `lp` | Later phase |
| Scripting | Expect-style login scripts | Later phase |
| Hotspots | Clickable on-screen text (e.g. `F3=Exit`) that sends a key | Later phase |
| IBM 3270 / 5250 | Block-mode emulations | Out of scope for now (separate protocol stack) |

## Architecture

```
cherminal/
  screen.py          Character grid, cursor, attributes, scrolling, scrollback
  emulation/         Byte stream -> screen operations, one parser per family
    vt.py            VT100/VT220/ANSI-SCO/Linux/xterm (ECMA-48 state machine)
    wyse.py          Wyse 50/60 native mode
  keymap.py          Key names, default keymaps, layering, escape notation
  config.py          Session profiles and keymap files (TOML)
  transport/         Byte pipes: local PTY, Telnet, SSH (paramiko), serial (pyserial)
  gui/               PyQt6 front end; the only package that imports Qt
```

The core (`screen`, `emulation`, `keymap`, `config`, the Telnet protocol
machine) is pure Python with no GUI dependency, so it is unit tested
headlessly and could sit behind another front end later.

Data flow: transport reader thread -> bytes -> emulation `feed()` -> screen
mutations -> widget repaint. Key press -> key name (e.g. `Shift+F3`) ->
keymap lookup (respecting application cursor/keypad mode) -> bytes or an
action -> transport `write()`. Emulator replies (DA, DSR, answerback) go
back through the same transport.

## Key mapping model

A key is named `[Ctrl+][Alt+][Shift+]<Key>`, for example `F5`,
`Shift+F1`, `Ctrl+Up`, `Keypad5`, `Backspace`. A binding value is either a
byte string in Cherminal escape notation or an action:

* `\e` ESC, `\r`, `\n`, `\t`, `\xHH`, `\\`, and caret notation `^A`..`^_`,
  `^?` (DEL), `\^` for a literal caret.
* `action:copy`, `action:paste`, `action:break`, `action:reset`,
  `action:macro:<name>`.

Keys may be qualified by mode: `app:Up` applies only while the host has
enabled application cursor keys (DECCKM), `kp:Keypad5` only while
application keypad mode (DECKPAM) is on.

Lookup order, last wins: the emulation's built-in table, then the keymap
file named by the session (`keymaps/<name>.toml`, which may `inherit`
another), then the session's own `[keys]` table. Common fixes such as
"Backspace sends ^H" or "Delete sends DEL" are one-line overrides.

## Session profile format

`~/.config/cherminal/sessions/<slug>.toml`:

```toml
name = "Warehouse AS/400 gateway"
transport = "telnet"          # ssh | telnet | serial | local
host = "10.0.0.5"
port = 23
emulation = "wyse60"          # vt100 vt220 vt320 vt420 ansi at386 linux xterm
                              # wyse50 wyse60 tvi925 tvi950 adm3a
encoding = "latin-1"
cols = 80
rows = 24
keymap = "warehouse"          # optional file in keymaps/
answerback = ""
backspace = "bs"              # del | bs

[keys]
F12 = "^AK\r"
"Ctrl+Shift+V" = "action:paste"

[macros]
login = "operator\r"
```

Passwords are never written to profiles. SSH uses keys or the agent, and
asks interactively otherwise.
