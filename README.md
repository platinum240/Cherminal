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
- **Right-click menu and search:** copy, paste, search and one-off colours;
  a search bar that looks up or down through the screen and scrollback.
- **File upload over SSH:** drop files on the window to send them to the
  host by SFTP, when the session allows it.
- **Printing:** Print Screen to a local (CUPS) printer or PDF, for 3270 and
  every other emulation, and host passthrough printing on VT sessions.
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

### Remapping keys on screen

In a session's Keyboard tab, **Keyboard map…** opens a picture of the
keyboard. Click a key (or **Find a key by pressing it…**), then pick what it
sends: a 3270 or terminal action, a macro, or your own text. Click the
Shift, Ctrl or Alt keys on the picture to map those layers. Keys you changed are
orange, keys the emulation already maps are blue. The changes are saved in
the session, so they travel with it when it is exported or shared; **Save
as keymap…** keeps them as a named keymap other sessions can use.

### Copying another emulator's keyboard

```sh
cherminal-keycapture --port 2323 --name tinyterm-wyse60 --inherit wyse
```

Then, from TinyTerm (or any emulator) set to the emulation you use, Telnet
to this machine on port 2323 and press each key it asks for. The keymap is
saved to `~/.config/cherminal/keymaps/tinyterm-wyse60.toml`.

## Logging in to SSH hosts as a different user

In a session's Connection tab, tick **Ask for user name and password when
connecting** for hosts where people log in with an account that isn't
their workstation login. Each connection then opens a login box with both
fields (the session's User, if set, is filled in as a suggestion). A wrong
password asks again. With this on, Cherminal signs in only with what was
typed, never with the workstation user's SSH keys or agent.

## Colours, high contrast and accessibility

The **Colours** tab of a session sets:

- **Scheme:** includes `high-contrast` (white on black), `high-contrast-light`
  (black on white), `yellow-on-black` and `black-on-yellow`.
- **Text, background and cursor** colours of your own.
- **Minimum contrast:** every colour the host uses is lightened or darkened
  just enough to reach the chosen WCAG ratio against the background
  (4.5:1 AA or 7:1 AAA), keeping its hue. The high-contrast schemes use 7:1.
  This fixes, for example, dark blue mainframe fields on a black screen.
- **Host colours:** replace any of the 16 base colours (3270 blue, red,
  pink, green, turquoise, yellow and white are the `bright-` ones).

A preview shows the result and the text's contrast ratio. The settings are
saved with the session and travel in exported and shared session files.

```toml
color_scheme = "high-contrast"
min_contrast = 7
cursor_color = "#ff00ff"
[palette]
bright-blue = "#80c0ff"
```

### Changing colours for one session only

**View › Colours for this session…** (also on the right-click menu) changes
the colours of the open window without touching the saved session. On a
shared machine the administrator sets the session's colours once, and a user
who needs, say, yellow on black or a higher contrast picks it just for
themselves. **Use the session's colours** goes back. The change lasts until
the tab is closed (it survives Session › Reconnect) and works in limited mode.

## Copy, paste and search

Right-click the screen for **Copy**, **Paste**, **Search…** and **Colours for
this session…**. Selecting with the mouse also fills the X11 primary
selection, and the middle button pastes it.

**Search…** (or Edit › Search…, Ctrl+Shift+F) opens a bar under the screen.
Type to find the nearest match above; **▲** / Enter searches up through
older text, **▼** / Shift+Enter searches down, and both wrap around. The
settings button on the right has **Match case**, **Match whole word** and
**Regular expression**. Esc closes the bar. Hidden text, such as a password
field, is never matched.

## Uploading files over SSH

File transfer is **off** unless a session turns it on, in the session's
**File transfer** tab (SSH sessions only):

```toml
file_transfer = true
upload_dir = "~/inbox"     # default: the user's home folder
```

Then drop files from the file manager onto the session window (or right-click
› Upload files…). Cherminal asks before sending, shows progress with a Cancel
button, and asks before replacing a file that already exists on the host.

- Files go by SFTP inside the session's own SSH connection: encrypted, to the
  host whose key was checked when it connected, as the user who signed in.
  The host's normal permissions apply.
- Only the file's name is used on the host; folders are not uploaded.
- An upload is written to `NAME.part` and renamed when complete, so a
  cancelled or broken upload never replaces a good file.

## Printing

**Print screen** prints what is on the screen as text, one page, with the
session name and time at the top. Hidden fields such as passwords print
blank. Use the Print (PrtSc) key, Ctrl+Shift+P, Session › Print screen… or
the right-click menu; the key can be remapped like any other
(`action:print-screen`). It works in limited mode.

In a session's **Printing** tab:

- **Printer:** with none chosen, Cherminal shows the print dialog each time,
  which also offers saving a PDF. With a printer chosen (or a CUPS printer
  name typed in), it prints straight to it without asking, which suits
  shared and limited-mode thin clients.
- **Let the host print to it:** VT sessions only. A host that sends
  `ESC [ 5 i` … `ESC [ 4 i` (printer controller mode, as Unix applications
  and TinyTerm's passthrough printing use) has that data sent unchanged to
  the printer with `lp -o raw`, so printer codes such as PCL work. On by
  default; turn it off to show the data on screen instead.

```toml
printer = "front-desk"     # CUPS printer name; omit to ask each time
host_print = true
```

Mainframe-started printing to a 3287 printer LU (TN3270E) is not included.

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
