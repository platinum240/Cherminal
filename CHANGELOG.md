# Changelog

Check what you are running with `cherminal --version` (or
`./Cherminal-*.AppImage --version`); the window title shows it too.

## 0.3.0

- Session files (`.cherminal`) carry connections with the keymaps they use.
  `--export` / `--import`, or Export… / Import… in the Sessions window.
- Shared setup folders: sessions in `$CHERMINAL_SITE_DIR`, `cherminal-config/`
  next to the AppImage, or `/etc/xdg/cherminal/` appear on every machine.
- `--list` shows where each session comes from.

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
