<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="cherminal/resources/cherminal-logo-dark.png">
    <img src="cherminal/resources/cherminal-logo-light.png" alt="Cherminal" width="420">
  </picture>
</p>

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
  IBM 3278/3279 models 2-5 for mainframes (TN3270), and IBM 5250 display
  stations (3179-2, 5251-11, 3477-FC) for IBM i / AS/400 (TN5250).
- **Connections:** SSH (keys, agent, password, host-key verification),
  Telnet (TTYPE, NAWS, binary, echo/SGA, optional TLS), TN3270, TN5250
  (with a fixed device name if wanted), serial ports, local shell.
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
- **Keep-alive, auto-reconnect and idle timeout:** keep-alives every 60
  seconds, optional reconnecting after a dropped connection, and a 15-minute
  idle disconnect by default that blanks the screen.
- **Session logs that look after themselves:** optional text logs that
  rotate at 1 MB and stay under 10 MB in all, plus a connection audit log to
  syslog/journald for administrators.
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

To add Cherminal to the applications menu with its icon (for the current
user, under `~/.local/share`), run `cherminal --install-desktop` once. This
works for the AppImage too (`./Cherminal-*.AppImage --install-desktop`).

### On eLux thin clients

Build an eLux package (EPM) from the AppImage with
`packaging/elux/build-epm.sh` and Unicon's `epkg` tool, then deploy it from
Scout. See [packaging/elux/README.md](packaging/elux/README.md).

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
› Upload files…; in limited mode only dropping works, since a file chooser
would let users browse the disk). Cherminal asks before sending, shows progress with a Cancel
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
  which also offers saving a PDF (except in limited mode, or where the site
policy sets `print_to_file = false`). With a printer chosen (or a CUPS printer
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
any secure TN3270 port. If the host's certificate comes from an in-house
CA, set `tls_ca_file` in the site policy (below) so the certificate can
still be checked; untick "Check the host's certificate" only as a last
resort. The character set defaults to EBCDIC code page 037 (US/Canada); set
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

Not yet supported: TN3270E (LU names, SysReq/Attn), 3287 printing and file
transfer (IND$FILE). For IBM i, see the next section.

## IBM i (TN5250)

Choose connection **telnet** and one of these emulations:

| Emulation | Display station | Screen |
|---|---|---|
| `ibm3179-2` | IBM 3179 model 2 (colour) | 24×80 |
| `ibm5251-11` | IBM 5251 model 11 (green screen) | 24×80 |
| `ibm3477-fc` | IBM 3477 model FC (colour, wide) | 24×80 and 27×132 |

`ibm3179-2` suits most systems. Use `ibm3477-fc` for programs that show
132-column screens; the window switches size when the host asks. Port 23
is the default; tick **Use TLS** for port 992 (secure Telnet on IBM i), with
the same certificate checking and `tls_ca_file` site setting as TN3270.
The character set defaults to EBCDIC code page 037; set e.g. `cp500`,
`cp273` or `cp1140` under Terminal › Character set if the system uses
another.

**Device name.** IBM i normally gives each connection a new virtual device
(`QPADEV0001`, ...). To pin a workstation to a fixed device, so that it gets
the same job, output queue or subsystem routing each time, fill in **Device
name** on the Connection tab (shown for 5250 emulations only): up to 10
characters, A-Z, 0-9, `@ # $ _`. In a profile file it is
`device_name = "SHOP01"`. It is sent as the NEW-ENVIRON `DEVNAME` variable
(RFC 4777). The device is created on IBM i if the system value QAUTOVRT
allows it. No user name or password is ever sent this way; you always sign
on at the sign-on screen.

Typing edits the screen locally and the AID keys send it. Typing a wrong
character (a letter in a numeric field, outside an input field) inhibits
the keyboard as on a real 5250: the status bar shows `X II` and the reason,
and **Reset** (Escape) clears it. Error messages from the host appear on
the error line and also need Reset. The default keyboard (built-in keymap
`ibm5250`):

| Key | 5250 key | Key | 5250 key |
|---|---|---|---|
| Enter | Enter | Keypad Enter | Field Exit |
| Keypad + | Field+ | Keypad − | Field− (negative number) |
| F1-F12 | F1-F12 | Shift+F1-F12 | F13-F24 |
| PageUp | Roll Down (previous page) | PageDown | Roll Up (next page) |
| Escape | Reset | Shift+Escape, Pause | Attention |
| SysReq (Alt+Print) | System Request | Ctrl+Pause | Clear |
| Ctrl+F1 | Help | Ctrl+D | Dup |
| Tab / Shift+Tab | Next / previous field | Home | First input field |
| End | End of field | Insert | Insert mode |
| Backspace | Erase left | Delete | Delete |
| Ctrl+End | Erase to end of field | Ctrl+Delete | Erase Input |
| Shift+Enter | New line | Ctrl+Print | Print (host print key) |

The Print key itself prints the screen locally, as for every session.
Any key can be remapped with `action:` and one of `enter`, `f1`-`f24`,
`field-exit`, `field-plus`, `field-minus`, `reset`, `attn`, `sysreq`,
`help`, `roll-up`, `roll-down`, `clear`, `print`, `record-backspace`,
`dup`, `field-mark`, `tab`, `backtab`, `home`, `newline`, `up`, `down`,
`left`, `right`, `field-end`, `insert`, `erase`, `delete`, `erase-eof`,
`erase-input`. Some PC 5250 users prefer Enter as Field Exit; put
`Enter = "action:field-exit"` and e.g. `KeypadEnter = "action:enter"` in
the session's key overrides, or in a keymap file with
`inherit = "ibm5250"` to share it.

The status bar shows the 5250 operator information: `X SYSTEM` while the
host has the keyboard locked, `X II` and a reason when input is inhibited,
`Insert`, `Message waiting`, and the cursor's row/column. Password
(non-display) fields are never drawn, so they cannot be copied, searched or
printed.

Not yet supported for 5250: 5250 printer sessions, windows and pull-down
menus drawn with structured fields (their text still shows), column
separator lines, and the SysReq input line (SysReq goes straight to the
host, which shows its System Request menu).

## Idle timeout, keep-alive and reconnecting

Settings are on the session's **Idle & reconnect** tab.

- **Disconnect when idle for** (15 minutes unless changed): when nobody has
  typed or clicked in the session for that long, Cherminal closes the
  connection and blanks the screen and scrollback, so an unattended
  terminal shows nothing. The status bar warns a minute before. Output from
  the host doesn't count as activity. Set it to **Never** to turn it off,
  unless the site policy caps it.
- **Keep-alive every** (60 seconds): keeps quiet connections from being
  dropped by firewalls and notices a dead link. SSH uses SSH keep-alives,
  Telnet and TN3270 send a Telnet NOP, and both turn on TCP keep-alive.
- **Reconnect automatically if the connection drops** (off): after a
  network drop Cherminal tries again after 2, 5, 10, 20, 30 and then every
  60 seconds, up to ten times. It doesn't reconnect when you log off, when
  the host closes the session, or after an idle timeout. SSH sessions that
  need a password ask for it again.

Whenever a session has ended, press **Enter** in it to connect again.

## Session logs

Turn on **Keep a log of this session's text** on the session's **Logging**
tab. Logs go to `~/.local/state/cherminal/logs/<session>.log`. A log holds
what the screen showed: lines as they scroll up, what was left on the
screen at the end and, for IBM 3270 sessions, each screen as it was sent
to the host. Hidden fields such as passwords are left blank, and
keystrokes are never logged.

Logs clean up after themselves, for thin clients with little space. Each
session starts a new file at 1 MB and keeps 2 older ones (both adjustable),
and all session logs together are kept under 10 MB by deleting the oldest
files. If the disk fills up, logging stops and the session carries on.

## Limited mode for shared workstations

```sh
./Cherminal-x86_64.AppImage --limited "Mainframe A" "Mainframe B"
```

`--limited` opens the named sessions with a File menu offering only
**Close tab** and **Exit**. Users can't open the session list, create or
edit sessions, use Quick connect or start a local shell, and those menu
shortcuts are gone too. Edit, View, Session and Help stay. Started with no
session names, it shows a list of the available sessions with only a
Connect button (local shell sessions are left out). Right-click › Upload
files… is not offered (dropping files still works where the session allows
it), and Print screen goes to printers only, never to a PDF file.

Put the command in the launcher or desktop icon the users start, for
example together with a shared setup folder below.

## Site policy (administrators)

An administrator can enforce settings that users cannot change, in
`/etc/cherminal/policy.toml` (owned by root). Cherminal reads only that
path, and no option or environment variable turns it off. Every setting is
optional; an empty file changes nothing.

```toml
limited = true                    # always limited mode, as with --limited
allowed_transports = ["telnet", "ssh"]
file_upload = false               # no SFTP upload, whatever the session says
print_to_file = false             # Print screen to printers only, never PDF
require_tls = false               # Telnet/TN3270 only over TLS (off by default)
require_tls_verify = false        # TLS must check the certificate (off by default)
tls_ca_file = "/etc/cherminal/ca.pem"   # extra CA certificates to trust for TLS
max_idle_timeout = 15             # minutes; sessions may be shorter, never longer or off
auto_reconnect = false            # never reconnect by itself after a drop
session_logging = "allowed"       # "allowed", "never" or "always"
log_dir = "/var/log/cherminal/%u" # where session logs go (%u = user name)
log_total_mb = 10                 # all session logs together stay under this
audit_log = true                  # connection log to syslog/journald
```

With `audit_log = true` each connection, disconnection and failed
connection is written to syslog (journald) as one line with the user,
session, host, what happened and how long it lasted, for example
`user=chad session='Payroll' transport=telnet host=mf1:23 event=disconnected
detail='closed by the user; after 0h42m10s'`. Nothing typed or shown in a
session is ever in it. Read it with `journalctl -t cherminal`.

The TLS settings are off by default so mainframes without TLS keep working;
turn them on once every host supports it. Sessions the policy doesn't allow
are hidden from the session list and refused if opened another way, with a
message saying why.

Check a file before deploying it with `cherminal --check-policy FILE`. A
policy file that has a mistake in it, or can't be read, stops Cherminal
from starting, so a typo never leaves clients unrestricted.
`packaging/elux/policy.toml.example` explains each setting, and the eLux
package can carry the policy (see [packaging/elux/README.md](packaging/elux/README.md)).

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

## License

Cherminal is licensed under the [Apache License, Version 2.0](LICENSE).
