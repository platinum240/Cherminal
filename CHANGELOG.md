# Changelog

Check what you are running with `cherminal --version` (or
`./Cherminal-*.AppImage --version`); the window title shows it too.

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
