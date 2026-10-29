# Changelog

Check what you are running with `cherminal --version` (or
`./Cherminal-*.AppImage --version`); the window title shows it too.

## 0.11.0

- SCO ANSI is listed as `scoansi` (it was `ansi`; sessions saved with
  `ansi` still open as SCO ANSI). Like the SCO console it now ignores the
  DEC keypad and cursor-key modes, so keypad Enter sends CR instead of
  `ESC O M` when the host has been told the terminal is a VT.
- New **Keypad Enter sends** setting (`keypad_enter_sends`): CR, CR LF or
  LF for the number-pad Enter, separate from Return, and winning over
  keypad application mode. Shift+Return now follows **Enter sends** too,
  and VT line feed/new line mode (`ESC [ 20 h`) makes Return send CR LF.
- Modern view, part 2: Graphite and Paper colours that follow the
  desktop (`modern_theme`); typing mistakes are explained under the field
  instead of locking the keyboard, and changed fields get a dot; numbered
  menu options and list rows can be clicked (double-click to choose, and
  only with a code that views a row); the scroll wheel pages with PF7/PF8.
- AppImage: starts on desktops without the xcb-util libraries ("xcb-cursor0
  or libxcb-cursor0 is needed to load the Qt xcb platform plugin"). The
  libraries Qt's X11 plugin needs now ship inside the AppImage.
- Modern view for IBM 3270 and 5250 sessions (View › Modern view,
  Ctrl+Shift+M, or the button beside the tabs): input fields are boxed,
  the field with the cursor is outlined, a click puts the cursor in a
  field, and a key bar under the screen turns the screen's `F3=Exit` style
  keys into buttons, with More keys (PA1, Clear, Attention, SysReq...) and
  Send. Sessions choose how they start with `view = "classic"` or
  `"modern"`; the site policy's `modern_view` can turn it off or make it
  the default. Nothing changes in what is sent to the host.
- Ports: the session editor shows which port "default" means (23, 992 with
  TLS, 22 for SSH), `host:2323` typed in the Host box sets the port, and a
  port outside 1-65535 is refused when the session is saved.
- macOS: Cherminal runs on Macs (macOS 12 and later, Apple Silicon and
  Intel), built as `Cherminal.app` in a `.dmg` and a `.pkg` by
  `packaging/build-macos.sh` and the new `macos` workflow. See
  [docs/MACOS.md](docs/MACOS.md).
- macOS keyboard: Control sends control codes, Command is for the menus
  (⌘C, ⌘V, ⌘W, ...), and a per-session **Option key** setting makes the
  left, both or neither Option key Alt. Help counts as Insert, and the 3270
  and 5250 layouts get Mac keys for Clear, Insert, SysReq, Print and
  Field+/− (Ctrl+Esc, Ctrl+I, ...).
- macOS folders: `~/Library/Application Support/Cherminal`,
  `~/Library/Logs/Cherminal` and `/Library/Application Support/Cherminal`
  (shared setup and `policy.toml`); a `~/.config/cherminal` copied from
  Linux is used as it is.
- macOS site policy from managed preferences (Jamf and other MDMs), domain
  `io.github.platinum240.cherminal`; `--check-policy` reads `.plist` files.
- The local shell starts your login shell from your account when `$SHELL`
  isn't set, and the session editor suggests the serial ports it finds.

## 0.10.0

- IBM i: TN5250 with the IBM 3179-2, 5251-11 and 3477-FC display stations,
  a 5250 keyboard (Field Exit, Field+/−, Attention, SysReq, Roll Up/Down)
  and a fixed device name per session.
- IBM 3270: IND$FILE file transfer (Session › Transfer file…) for TSO,
  CICS and VM/CMS; paste that fills input fields and respects numeric
  fields; clickable PF keys (`PF3=Exit`, `ENTER`, ...) on the screen;
  TN3270E with LU names; and 3287 printer sessions that print mainframe
  jobs through CUPS unattended. Policy: `file_download`.
- Idle timeout: sessions disconnect after 15 minutes without typing or
  clicking and blank the screen and scrollback. Adjust or turn it off per
  session; the policy's `max_idle_timeout` caps it. **This is on by
  default.**
- Keep-alives every 60 seconds (SSH, Telnet NOP and TCP), and an optional
  automatic reconnect after a dropped connection (not after logging off).
  Press Enter in a session that has ended to connect again.
- Session logs: optional text logs with hidden fields left blank and no
  keystrokes, rotating at 1 MB, 2 older files kept, and all logs held
  under 10 MB. Policy: `session_logging`, `log_dir`, `log_total_mb`.
- Audit log: with `audit_log = true` each connection, disconnection and
  failure goes to syslog/journald.
- SSH host keys in `/etc/ssh/ssh_known_hosts` and in shared setup folders
  are trusted without asking; `ssh_known_hosts_only = true` refuses any
  other host.
- An administrator guide (docs/ADMIN.md) and a user guide (docs/USER.md).

## 0.9.0

- Site policy: an administrator's `/etc/cherminal/policy.toml` enforces
  limited mode, which connections are allowed, SFTP upload, printing to a
  file, and optionally TLS for Telnet/TN3270, certificate checking and an
  in-house CA to trust. `cherminal --check-policy FILE` checks one first.
  A broken policy stops Cherminal instead of running unrestricted.
- Limited mode no longer offers a file chooser (right-click › Upload
  files…) or printing to a PDF file.
- A host can no longer freeze the client with endless or oversized escape
  sequences, 3270 records or Telnet subnegotiations, or huge repeat counts.
- eLux package: `packaging/elux/build-epm.sh` builds the package tree for
  Unicon's `epkg`, and the release workflow publishes it.
- Licensed under the Apache License 2.0.

## 0.8.3

- No "Failed to register with host portal" warnings at start-up, whether or
  not Cherminal has a desktop menu entry.
- `cherminal --install-desktop` adds a menu entry and the Cherminal icon
  under `~/.local/share`, so pip installs and AppImages show in the
  applications menu and the taskbar with the logo.

## 0.8.2

- No more "Failed to register with host portal" warning at start-up on
  desktops with xdg-desktop-portal.

## 0.8.1

- The Cherminal logo is the window, taskbar and AppImage icon, and appears
  in Help › About.

## 0.8.0

- Print screen (Print key, Ctrl+Shift+P, Session menu, right-click) to a
  local printer or PDF, with hidden fields left blank.
- A session's Printing tab: a fixed printer to print to without asking, and
  host passthrough printing (ESC [ 5 i … ESC [ 4 i) for VT sessions, sent raw
  through CUPS.
- The Print and SysReq keys can be mapped.

## 0.7.0

- Colours for this session: change an open window's colours (scheme,
  contrast, any colour) without changing the saved session.
- Right-click menu with Copy, Paste, Search and Colours.
- Search bar: up/down through screen and scrollback, with Match case, Match
  whole word and Regular expression.
- Drop files on an SSH session to upload them by SFTP. Off by default; turn
  it on in the new File transfer tab, with an optional destination folder.

## 0.6.0

- Keyboard map…: remap keys by clicking them on an on-screen keyboard, with
  the Shift/Ctrl/Alt layers and the 3270 actions to choose from.

## 0.5.0

- SSH sessions can ask for user name and password together when connecting,
  for host logins that differ from the workstation login.
- High-contrast colour schemes, custom text/background/cursor colours,
  replaceable host colours, and a minimum contrast (WCAG AA/AAA) applied to
  every colour the host uses. New Colours tab with a live preview.

## 0.4.0

- `--limited`: the File menu offers only Close tab and Exit, with no way to
  open, create or edit sessions or start a local shell.

## 0.3.0

- Session files (`.cherminal`) carry connections with the keymaps they use.
  `--export` / `--import`, or Export… / Import… in the Sessions window.
- Shared setup folders: sessions in `$CHERMINAL_SITE_DIR`, `cherminal-config/`
  next to the AppImage, or `/etc/xdg/cherminal/` appear on every machine.
- `--list` shows where each session comes from.
- IBM 3278/3279 models 2-5 over TN3270, with colour, extended highlighting,
  PF1-24/PA1-3/Clear and field editing keys, and the 3270 status (keyboard
  locked, insert, cursor position) in the status bar.
- Telnet over TLS (port 992 by default), with an option for hosts whose
  certificate comes from an in-house CA.

## 0.2.0

- Text scales with the window by default; the host keeps its fixed grid.
  Per session "When the window resizes", or View › Scale text to window.
- SSH asks for a password when there is no key or agent, instead of failing
  with "No authentication methods available".
- Connections close cleanly on tab close, window close, Ctrl+C, SIGTERM and
  SIGHUP, including a tab closed while still connecting.
- Self-contained AppImage for workstations without internet access.
- `--version` option; version shown in the window title.

## 0.1.0

- First release: VT/ANSI/Wyse/TVI emulations, SSH/Telnet/serial/local
  connections, layered key mapping, saved sessions, key capture tool.
