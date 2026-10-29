# Cherminal administrator guide

This guide is for the people who install Cherminal on workstations and thin
clients, set up the sessions users connect with, and decide what users may
change. For using Cherminal day to day, see the [user guide](USER.md).
For Macs (folders, Jamf and managed preferences, signing), see
[MACOS.md](MACOS.md); the rest of this guide applies to them too.

- [1. What gets installed where](#1-what-gets-installed-where)
- [2. Installing](#2-installing)
- [3. Sharing sessions and keymaps](#3-sharing-sessions-and-keymaps)
- [4. The site policy](#4-the-site-policy)
- [5. Locking a workstation down](#5-locking-a-workstation-down)
- [6. TLS and certificates](#6-tls-and-certificates)
- [7. SSH host keys](#7-ssh-host-keys)
- [8. Idle timeout, keep-alive and reconnecting](#8-idle-timeout-keep-alive-and-reconnecting)
- [9. Session logs and the audit log](#9-session-logs-and-the-audit-log)
- [10. Printing](#10-printing)
- [11. IBM mainframes and IBM i](#11-ibm-mainframes-and-ibm-i)
- [12. Rolling out to eLux thin clients with Scout](#12-rolling-out-to-elux-thin-clients-with-scout)
- [13. Updating](#13-updating)
- [14. Troubleshooting](#14-troubleshooting)
- [Appendix: session settings](#appendix-session-settings)

## 1. What gets installed where

| What | Where | Who writes it |
|---|---|---|
| The program | The AppImage file, or `/opt/cherminal` on eLux, or a Python install | You |
| Site policy | `/etc/cherminal/policy.toml` (fixed path) | You (root) |
| Shared sessions and keymaps | `/etc/xdg/cherminal/`, `cherminal-config/` next to the AppImage, or folders in `$CHERMINAL_SITE_DIR` | You |
| Trusted SSH host keys | `/etc/ssh/ssh_known_hosts`, and `known_hosts` in any shared folder | You |
| A user's own sessions and keymaps | `~/.config/cherminal/sessions/`, `~/.config/cherminal/keymaps/` | The user |
| SSH host keys a user accepted | `~/.config/cherminal/known_hosts` | Cherminal |
| Session logs | `~/.local/state/cherminal/logs/`, or the policy's `log_dir` | Cherminal |
| Audit log | syslog / journald, tag `cherminal` | Cherminal |
| Menu entry and icon (optional) | `~/.local/share/applications`, `~/.local/share/icons` | `cherminal --install-desktop` |

Cherminal never stores passwords. Session files are plain TOML text, so you
can read, diff and version them.

## 2. Installing

**AppImage (any x86_64 Linux from about 2019 on, no internet needed).**
Copy `Cherminal-<version>-x86_64.AppImage` to the machine and make it
executable. It carries its own Python and Qt. If it reports a FUSE error,
install `libfuse2` (or `fuse-libs`) or run it with
`--appimage-extract-and-run`.

**pip.** `pip install .` from a checkout, on Python 3.11 or newer. This
installs the `cherminal` and `cherminal-keycapture` commands.

**eLux.** See [section 12](#12-rolling-out-to-elux-thin-clients-with-scout).

**Menu entry.** `cherminal --install-desktop` (or
`./Cherminal-*.AppImage --install-desktop`) adds Cherminal with its icon to
the applications menu for the user who runs it. The eLux package installs
the menu entry for everyone. Without a menu entry Cherminal still runs; it
only hides a harmless warning from the desktop portal.

**Serial ports.** Users need to be in the `dialout` group (or your
distribution's equivalent) to open `/dev/ttyS*` and `/dev/ttyUSB*`.

## 3. Sharing sessions and keymaps

Set sessions up once on any machine, then export them to a `.cherminal`
file, which holds the sessions together with every custom keymap they use:

```sh
cherminal --export mainframes.cherminal "Mainframe A" "Payroll"
```

(or select them in **File › Sessions** and press **Export…**).

**Shared setup (recommended).** Put the file in a folder Cherminal reads at
start-up. Every user then sees those sessions, marked `[shared]`, and
changes reach everyone the next time the Sessions window opens. Nothing is
copied into home folders, so it also works where homes are wiped at logoff.
Cherminal looks in these folders, and the first one with a given session
name wins:

1. each folder in `$CHERMINAL_SITE_DIR` (`:`-separated), for example a
   mounted network share;
2. `cherminal-config/` next to the AppImage, so a copied folder travels
   with it;
3. `/etc/xdg/cherminal/` (each folder in `$XDG_CONFIG_DIRS`).

Each folder may hold `*.cherminal` files, plus `sessions/` and `keymaps/`
folders laid out like `~/.config/cherminal`, and a `known_hosts` file
([section 7](#7-ssh-host-keys)). If a user edits a shared session, their
copy is saved in their own folder and shown as `[shared, edited here]`;
deleting it brings the shared one back. To stop users editing at all, use
limited mode ([section 5](#5-locking-a-workstation-down)).

**Import.** `cherminal --import mainframes.cherminal` copies the sessions
and keymaps into the user's own folder instead.

**Keyboards.** To carry an existing TinyTerm (or other emulator) keyboard
across, run `cherminal-keycapture` against the old emulator; it records
what each key sends and saves a keymap. Put the keymap in a shared
`keymaps/` folder and set `keymap = "<name>"` in the sessions.

Every setting a session file can have is listed in the
[appendix](#appendix-session-settings).

## 4. The site policy

The policy is one TOML file at `/etc/cherminal/policy.toml` (on a Mac,
`/Library/Application Support/Cherminal/policy.toml`, or a configuration
profile: see [MACOS.md](MACOS.md#managing-cherminal-with-jamf-or-another-mdm)),
owned by root and readable by everyone. Cherminal reads only that path; no option or
environment variable points it elsewhere or turns it off. Every setting is
optional, and a missing or empty file changes nothing.

A policy file that has a mistake in it, or can't be read, stops Cherminal
from starting, so a typo never leaves clients unrestricted. Check a file
before you deploy it:

```sh
cherminal --check-policy policy.toml
```

It prints every setting the file enforces. A commented example with every
setting is in `packaging/elux/policy.toml.example` (installed on eLux as
`/etc/cherminal/policy.toml.example`).

| Setting | Default | What it does |
|---|---|---|
| `limited` | `false` | Always run in limited mode ([section 5](#5-locking-a-workstation-down)). |
| `allowed_transports` | all | The kinds of connection users may open: `ssh`, `telnet`, `serial`, `local`. Sessions using others are hidden and refused. |
| `file_upload` | `true` | `false` turns off SFTP upload (drag and drop) and IND$FILE sending to a mainframe. |
| `file_download` | `true` | `false` turns off IND$FILE receiving from a mainframe. |
| `print_to_file` | `true` | `false` makes Print screen offer printers only, never a PDF file. |
| `require_tls` | `false` | Telnet, TN3270 and TN5250 only over TLS. |
| `require_tls_verify` | `false` | TLS sessions must check the host's certificate. |
| `tls_ca_file` | none | Extra CA certificates (PEM) to trust for TLS. |
| `ssh_known_hosts_only` | `false` | SSH only to hosts whose keys you provided ([section 7](#7-ssh-host-keys)). |
| `max_idle_timeout` | none | Longest idle timeout in minutes; sessions may be shorter but not longer or off. |
| `auto_reconnect` | `true` | `false` stops sessions reconnecting by themselves after a drop. |
| `session_logging` | `"allowed"` | `"never"` or `"always"` overrides each session's logging setting. |
| `log_dir` | per user | Where session logs go; `%u` is replaced with the user name. |
| `log_total_mb` | `10` | All session logs together stay under this size. |
| `audit_log` | `false` | Write connection events to syslog/journald. |
| `modern_view` | `"allowed"` | 3270/5250 Modern view: `"off"` keeps everyone on the classic screen, `"default"` starts sessions in Modern view unless they choose Classic. |

Settings the policy decides are greyed out in the session editor with a
tooltip saying so. Sessions the policy doesn't allow show a message saying
why when someone tries to open them.

## 5. Locking a workstation down

**Limited mode** is for shared and kiosk-style machines. Start Cherminal
with `--limited` and the sessions to open, or set `limited = true` in the
policy:

```sh
cherminal --limited "Mainframe A" "Payroll"
```

In limited mode the File menu offers only **Close tab** and **Exit**. Users
can't open the session list to edit, create or delete sessions, can't use
Quick connect or start a local shell, can't pick local files to upload, and
can't print to a PDF file. IND$FILE transfer is off in limited mode unless
the policy says `file_upload = true` or `file_download = true` in so many
words, and then it only reads and writes files directly in the user's
Downloads folder, with no file browser. Started with no session names, it shows the
available sessions with only a **Connect** button. Users can still copy,
paste, search, change colours for the current session, print to a printer
and reconnect.

A typical locked-down mainframe client's policy:

```toml
limited = true
allowed_transports = ["telnet"]
print_to_file = false
require_tls = true
require_tls_verify = true
tls_ca_file = "/etc/cherminal/ca.pem"
max_idle_timeout = 15
audit_log = true
```

Put the command with `--limited` and the session names in the launcher or
Scout application entry users start.

## 6. TLS and certificates

Tick **Use TLS** in a Telnet session for secure TN3270 or TN5250, usually
on port 992 (the default port when TLS is on). Cherminal checks the host's
certificate against the system's CA store by default.

If your hosts' certificates come from an in-house CA, put the CA
certificate (PEM) on the clients and set
`tls_ca_file = "/etc/cherminal/ca.pem"` in the policy, so checking stays
on. Turning off **Check the host's certificate** in a session is a last
resort; `require_tls_verify = true` forbids it.

`require_tls` is off by default because some hosts don't offer TLS. Turn it
on once every host supports it; sessions without TLS are then refused.

## 7. SSH host keys

The first time a user connects to an SSH host, Cherminal shows the host's
key fingerprint and asks whether to trust it; the answer is saved in
`~/.config/cherminal/known_hosts`. A host key that changes is always
refused, with a message showing the new key.

To spare users that question, and to stop them trusting a wrong key,
provide the keys yourself. Cherminal trusts, without asking:

- `/etc/ssh/ssh_known_hosts`, the system-wide OpenSSH file;
- `known_hosts` in each shared setup folder ([section 3](#3-sharing-sessions-and-keymaps));
- the user's own `~/.ssh/known_hosts`.

Collect keys from a trusted network and check their fingerprints with the
host's owner:

```sh
ssh-keyscan -t ed25519,rsa host1.example.com host2.example.com > known_hosts
ssh-keygen -lf known_hosts
```

For a host on a port other than 22, the entry starts `[host]:port`.

With `ssh_known_hosts_only = true` in the policy, Cherminal refuses any SSH
host whose key isn't in one of those files, never asks, and never saves a
key.

## 8. Idle timeout, keep-alive and reconnecting

Each session has these settings on its **Idle & reconnect** tab:

| Setting | Default | |
|---|---|---|
| `idle_timeout` | `15` | Minutes without typing or clicking before Cherminal disconnects; `0` = never. |
| `keepalive` | `60` | Seconds between keep-alives; `0` = off. |
| `auto_reconnect` | `false` | Reconnect by itself after a dropped connection. |

**Idle timeout.** Only the user's typing and clicking count as activity;
output from the host doesn't. A minute before the timeout the status bar
warns. When it fires, Cherminal closes the connection and blanks the screen
and scrollback, so an unattended terminal shows nothing. Pressing Enter
connects again. `max_idle_timeout` in the policy caps it for every
session: a session set to `0` (never) or to a longer time uses the cap.

**Keep-alive.** Keeps quiet connections from being dropped by firewalls
and NAT, and lets Cherminal notice a dead connection. SSH sessions send SSH
keep-alives, Telnet sessions (including TN3270 and TN5250) send a Telnet NOP,
and both turn on TCP keep-alive probes.

**Reconnecting.** With `auto_reconnect = true`, when a connection breaks
(reset, timed out, the network went away) Cherminal tries again after 2, 5,
10, 20, 30 and then every 60 seconds, up to ten tries. It does not
reconnect when the user logs off, the host closes the session, the user
disconnects, or the idle timeout fires. SSH sessions that need a password
ask for it again. `auto_reconnect = false` in the policy turns it off
everywhere.

## 9. Session logs and the audit log

### Session logs

A session log is a text file of what the session's screen showed: lines as
they scroll off the top, what was left on screen at the end, and, for IBM
3270 and 5250 sessions, each screen as it was sent to the host. Hidden
fields such as passwords are written as blanks, and keystrokes are never
logged, so a password typed at a prompt that doesn't echo it is not in the
log. Each connection starts and ends with a marked line with the time.

Logging is off unless a session turns it on (**Logging** tab), or the
policy says `session_logging = "always"`. `session_logging = "never"`
turns it off everywhere.

Logs are kept small for thin clients:

| Setting | Default | |
|---|---|---|
| `log_file_kb` (session) | `1024` | Start a new file at this size. |
| `log_keep` (session) | `2` | Older files kept per session (`name.log.1`, `name.log.2`); older ones are deleted. |
| `log_total_mb` (policy) | `10` | All logs in the folder together; the oldest files go first. |

So by default each session uses at most about 3 MB and all of them together
at most 10 MB. If the disk fills up, logging stops and the session carries
on. Files are created readable by the user only (mode 600).

Logs go to `~/.local/state/cherminal/logs/` unless the policy sets
`log_dir`, for example a network share: `log_dir = "/mnt/logs/cherminal/%u"`
(`%u` is the user name). The folder is created if needed; the user must be
allowed to write there.

### Audit log

With `audit_log = true` Cherminal writes one line to syslog (journald on
most systems, facility `auth`, tag `cherminal`) for every connection,
disconnection and failed connection:

```
cherminal[4242]: user=chad session='Payroll' transport=telnet host=mf1.example.com:992 event=connected
cherminal[4242]: user=chad session='Payroll' transport=telnet host=mf1.example.com:992 event=disconnected detail='idle for 15 minutes; after 0h42m10s'
cherminal[4242]: user=chad session='Payroll' transport=telnet host=mf1.example.com:992 event=connect-failed detail='[Errno 111] Connection refused'
```

Failures and dropped connections are logged at warning level, the rest at
info. Nothing typed or shown in a session is ever in the audit log. Read it
with `journalctl -t cherminal`, and forward it to your central log server
the way you forward other syslog messages.

## 10. Printing

Cherminal prints through CUPS. Set up the printers on the client as usual
(on eLux, through Scout's printer settings).

- **Print screen** (Print key, Ctrl+Shift+P, Session › Print screen, or
  the right-click menu) prints the screen as text, hidden fields blank.
- A session's **Printing** tab can name a printer, which is then used
  without asking. This suits shared and limited-mode machines. With none
  set, users choose a printer each time.
- **Host passthrough printing** on VT sessions (`ESC [ 5 i` ... `ESC [ 4 i`)
  sends the host's print job to the printer unchanged with `lp -o raw`.
  Untick it per session if hosts shouldn't print.
- `print_to_file = false` in the policy (or limited mode) removes printing
  to a PDF file.

## 11. IBM mainframes and IBM i

**TN3270 (z/OS and other mainframes).** Use a Telnet session with emulation
`ibm3278-2` (24×80), `ibm3278-3` (32×80), `ibm3278-4` (43×80) or
`ibm3278-5` (27×132). The keyboard is the built-in `ibm3270` keymap; see
the README for the key table.

**TN5250 (IBM i).** Use a Telnet session with emulation `ibm3179-2`
(colour, 24×80), `ibm5251-11` (green screen) or `ibm3477-fc` (also 27×132).
To give a workstation a fixed virtual device, set **Device name** on the
Connection tab (`device_name = "SHOP01"`, up to 10 characters A-Z, 0-9,
`@ # $ _`). The system value QAUTOVRT must allow IBM i to create it. No user
name or password is sent this way.

**LU names (TN3270E).** Leave **LU name** empty and Cherminal uses plain
TN3270, with the host picking the terminal. Where your site gives each
workstation or printer its own LU, fill it in (`lu_name = "TSO0042"`, up to
8 characters); Cherminal then negotiates TN3270E and asks for that LU. If
the host refuses it, the session says why.

**3287 printer sessions.** A session with emulation `ibm3287-1` connects to
a printer LU and prints what the mainframe sends, with no user and no
dialogs: SCS and 3270 print data become text pages sent to the session's
printer (Printing tab) through CUPS, or the default printer. Start it
alongside the display session, for example from the same launcher.
Printer sessions are never disconnected by the idle timeout; turn on
`auto_reconnect` for them so they come back after a network drop.

```toml
name = "Payroll printer"
transport = "telnet"
host = "mvs.example.com"
emulation = "ibm3287-1"
lu_name = "PRT0042"
printer = "payroll-laser"
auto_reconnect = true
```

**File transfer (IND$FILE).** Session › Transfer file… sends or receives a
file with IBM's IND$FILE program, which must be installed on the host, for
TSO, CICS and VM/CMS. `file_upload = false` and `file_download = false` in
the policy turn each direction off. The idle timeout doesn't fire while a
transfer runs.

**Paste and clickable keys.** Pasting into a 3270 screen fills input
fields only, and stops at a numeric field that would get letters. Key
names on the screen, such as `PF3=Exit` and `ENTER`, can be clicked; turn
that off per session with `hotspots = false`.

**Modern view.** Users can switch a 3270 or 5250 tab to Modern view: boxed
input fields, click to move the cursor, clickable menu options and list
rows, typing errors explained beside the field, wheel paging, and a bar of
buttons for the keys the screen lists. It only changes how the screen is drawn and what the
mouse does; the data sent to the host is the same. A session's
`view = "modern"` or `"classic"` picks how it starts, and the policy's
`modern_view` turns it off or makes it the default for sessions that don't
choose.

**Other ports.** Some TN3270 servers offer extra ports that skip the
front screen and go straight to an application or a submenu (for example
2323). Give each its own session with `port = 2323`, or type `host:2323`
in the Host box.

Both 3270 and 5250 default to EBCDIC code page 037. Set another (`cp500`, `cp273`,
`cp1140`, ...) under Terminal › Character set if your system uses one. Use
TLS on port 992 where the host offers it ([section 6](#6-tls-and-certificates)).

## 12. Rolling out to eLux thin clients with Scout

1. **Build the package.** From a release AppImage, run
   `packaging/elux/build-epm.sh Cherminal-<version>-x86_64.AppImage`, then
   `epkg Build` in the eLux SDK VM. The full steps, including signing, are
   in [packaging/elux/README.md](../packaging/elux/README.md). The package
   installs Cherminal in `/opt/cherminal` with its own Python and Qt, so
   clients need no FUSE.
2. **Add your policy.** Write and check `policy.toml`, then save it as
   `packaging/elux/site/policy.toml` before building. The build adds a
   `cherminal-policy` part that installs it as
   `/etc/cherminal/policy.toml`.
3. **Add shared sessions, keymaps and host keys.** Deploy your
   `.cherminal` file, `keymaps/` and `known_hosts` to `/etc/xdg/cherminal/`
   (or a share named in `$CHERMINAL_SITE_DIR`), and your CA certificate to
   the path in `tls_ca_file`.
4. **Import and assign.** Import the `.epm`/`.fpm` files into ELIAS and add
   them to the clients' image in Scout. Make sure the signing certificate
   is deployed to `/setup/cacerts/` first.
5. **Add an application entry** whose command is, for example,
   `cherminal --limited "Mainframe A"`.
6. **Try one client** before assigning the image to everyone: start the
   session, check the policy with `cherminal --check-policy
   /etc/cherminal/policy.toml`, and look for the audit lines with
   `journalctl -t cherminal` if you turned them on.

## 13. Updating

Replace the AppImage, or build and assign a new eLux package. Settings,
sessions, keymaps, known hosts and logs are kept. `cherminal --version`
shows the installed version, and [CHANGELOG.md](../CHANGELOG.md) lists what
changed. New settings always default to the old behaviour, except where the
changelog says otherwise.

## 14. Troubleshooting

| Symptom | What to do |
|---|---|
| Cherminal won't start and names `/etc/cherminal/policy.toml` | The policy has a mistake. Run `cherminal --check-policy /etc/cherminal/policy.toml` for the exact line. |
| A session is missing from the list or won't open | The policy doesn't allow its connection type or requires TLS; the message says which. |
| "certificate verify failed" | The host's certificate isn't from a trusted CA. Set `tls_ca_file` ([section 6](#6-tls-and-certificates)). |
| "is not a known host" | `ssh_known_hosts_only` is on and the host's key isn't provided ([section 7](#7-ssh-host-keys)). |
| "host key ... has CHANGED" | The host's key differs from the saved one. Check with the host's owner before removing the old line from `known_hosts`. |
| AppImage: FUSE error | Install `libfuse2`, or run with `--appimage-extract-and-run`. |
| `qt.qpa.services` portal warning in a terminal | Harmless. `cherminal --install-desktop` registers Cherminal and silences it. |
| Sessions disconnect after 15 minutes | That is the default idle timeout ([section 8](#8-idle-timeout-keep-alive-and-reconnecting)). |
| Connections drop after a few minutes of quiet | A firewall closes idle connections. Lower `keepalive` (for example 30 seconds) and consider `auto_reconnect`. |
| No session log appears | Check the session's Logging tab and the policy's `session_logging`; a status bar message reports a folder that can't be written. |
| Keys send the wrong thing | Use `cherminal-keycapture` against the old emulator, or the **Keyboard map…** editor on the session's Keyboard tab. |

## Appendix: session settings

A session file (`sessions/<name>.toml`, or a `[[session]]` table in a
`.cherminal` file) holds any of these. Leave out a setting to use its
default.

| Setting | Default | Meaning |
|---|---|---|
| `name` | `"New session"` | Shown in the session list and on the tab. |
| `transport` | `"ssh"` | `ssh`, `telnet`, `serial` or `local`. |
| `host` | | Host name or address. |
| `port` | `0` | 0 = the usual port (22 SSH, 23 Telnet, 992 Telnet with TLS); any other, such as `2323`, connects there. |
| `tls` | `false` | Telnet/TN3270/TN5250 over TLS. |
| `tls_verify` | `true` | Check the host's certificate. |
| `device_name` | | TN5250 device name, up to 10 of A-Z 0-9 @ # $ _. |
| `lu_name` | | TN3270E LU to connect to (display or printer), up to 8 characters. |
| `username` | your login | SSH user name. |
| `identity_file` | | SSH private key file. |
| `ask_login` | `false` | SSH: ask for user name and password when connecting. |
| `file_transfer` | `false` | SSH: allow uploading dropped files (SFTP). |
| `upload_dir` | home folder | SSH: where uploads go; `~/` means the home folder. |
| `command` | login shell | Local shell: program to run. |
| `serial_device` | `"/dev/ttyUSB0"` | Serial port. |
| `baud`, `data_bits`, `parity`, `stop_bits`, `flow_control` | `9600`, `8`, `"none"`, `1`, `"none"` | Serial line settings; parity `none`/`even`/`odd`/`mark`/`space`, flow control `none`/`xonxoff`/`rtscts`. |
| `emulation` | `"vt220"` | Terminal type, for example `vt100`, `xterm`, `wyse60`, `ibm3278-2`, `ibm3179-2`, or `ibm3287-1` for a printer session. |
| `encoding` | emulation's | Character set, for example `cp037`, `latin-1`. |
| `cols`, `rows` | `80`, `24` | Screen size. |
| `scrollback` | `2000` | Lines kept above the screen. |
| `font_family`, `font_size` | `"Monospace"`, `11` | Font. |
| `color_scheme` | `"classic"` | Colour scheme. |
| `fg_color`, `bg_color`, `cursor_color` | scheme's | `"#rrggbb"`. |
| `min_contrast` | scheme's | Minimum contrast ratio for all text (4.5 = WCAG AA, 7 = AAA). |
| `palette` | | Replacement ANSI colours, for example `blue = "#6fa8ff"`. |
| `keymap` | emulation's | Name of a keymap file. |
| `backspace` | keymap's | `"del"` or `"bs"`. |
| `answerback` | | Text sent when the host asks for the answerback. |
| `local_echo` | `false` | Show typed characters locally. |
| `enter_sends` | `"cr"` | `cr`, `crlf` or `lf`. |
| `resize_mode` | `"scale"` | `scale` (text fits the window) or `grow` (add rows and columns). |
| `hotspots` | `true` | 3270: click key names such as `PF3=Exit` on the screen. |
| `view` | site default | 3270/5250: `"classic"` or `"modern"` (boxed fields, click to move, key buttons). |
| `modern_theme` | `"auto"` | Modern view colours: `"auto"` (Graphite or Paper, following the desktop), `"graphite"`, `"paper"`, or `"session"` for the session's own colours. |
| `printer` | ask | CUPS printer to use without asking (and for 3287 printer sessions). |
| `host_print` | `true` | VT: allow host passthrough printing. |
| `keepalive` | `60` | Seconds between keep-alives; 0 = off. |
| `auto_reconnect` | `false` | Reconnect after a dropped connection. |
| `idle_timeout` | `15` | Minutes without input before disconnecting; 0 = never. |
| `log_session` | `false` | Keep a session log. |
| `log_file_kb` | `1024` | Start a new log file at this size (KB). |
| `log_keep` | `2` | Older log files kept per session. |
| `keys` | | Key overrides, for example `"Ctrl+Enter" = "action:enter"`. |
| `macros` | | Named macros shown on the function-key bar. |
