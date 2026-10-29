# Cherminal on Windows

Cherminal runs on 64-bit Windows 10 (version 1809 or later) and Windows 11
with the same emulations, connections, key mapping, saved sessions,
printing and site policy as on Linux and macOS. This page covers what is
different on Windows: installing and deploying it, the keyboard, where
files live, and building it. Everything else is in the
[user guide](USER.md) and the [administrator guide](ADMIN.md).

Windows support is new in 0.13.0. It is built and tested on GitHub's
Windows runners; please report anything that behaves differently from
Linux on a real Windows PC.

## Installing

Each release has two Windows downloads:

- `Cherminal-<version>-windows-x64.msi`: installs Cherminal for everyone
  into `C:\Program Files\Cherminal` with a Start menu entry. Needs
  administrator rights. This is the one to deploy with Intune,
  Configuration Manager or Group Policy software installation.
- `Cherminal-<version>-windows-x64.zip`: portable. Unzip it anywhere and
  run `Cherminal.exe`; no administrator rights, no Start menu entry.

The app carries its own Python and Qt; nothing else is needed. Windows on
ARM PCs run the x64 build.

**Unsigned builds.** Until releases are code-signed, a downloaded copy
makes SmartScreen say "Windows protected your PC": choose More info, then
Run anyway. Copies deployed by Intune or Configuration Manager don't ask.
Companies that only allow signed software (AppLocker, App Control) need
to wait for signed releases or allow the app by path or file hash.

**Silent install and upgrade.**

```bat
msiexec /i Cherminal-0.13.0-windows-x64.msi /qn
msiexec /x Cherminal-0.13.0-windows-x64.msi /qn
```

A newer `.msi` replaces the installed version in place; users' sessions
are untouched. Uninstalling leaves `%ProgramData%\Cherminal` and anything
an administrator put there.

**Command line.** `Cherminal.exe` is the windowed app and prints nothing.
`cherminal-cli.exe`, in the same folder, takes the same options and prints
to the console:

```bat
"C:\Program Files\Cherminal\cherminal-cli.exe" --version
"C:\Program Files\Cherminal\cherminal-cli.exe" --list
"C:\Program Files\Cherminal\cherminal-cli.exe" --check-policy policy.toml
"C:\Program Files\Cherminal\cherminal-cli.exe" keycapture --name mykeys
"C:\Program Files\Cherminal\Cherminal.exe" "Mainframe A"
```

A pip install (`pip install .` on Python 3.11 or later) works too and gives
the `cherminal` and `cherminal-keycapture` commands.

## The keyboard

Cherminal reads the keyboard the same way as on Linux: Ctrl sends control
codes, Alt is Alt, and the menus' shortcuts are Ctrl+Shift+letter (Ctrl+Shift+C
copy, Ctrl+Shift+V paste, Ctrl+Shift+F search, Ctrl+Shift+P print screen).
Session files, keymaps and bundles are the same on every system.

Windows keeps a few keys for itself, so the built-in IBM keymaps add
others for what those keys do on Linux:

| Windows takes | So in a session use | 3270 | 5250 |
|---|---|---|---|
| Ctrl+Pause (arrives as Ctrl+Break) | Ctrl+Break, or Pause | Clear | Clear (Pause is Attention) |
| Print Screen (opens the Snipping Tool on Windows 11) | Ctrl+Shift+P for print screen | Print screen | |
| Ctrl+Print Screen | Ctrl+P | | Host print |
| Alt+Print Screen (copies the window) | Shift+Pause | | System Request |
| Ctrl+Esc (Start menu), Alt+Tab, Alt+F4, the Windows key | not available to sessions | | |

Windows 11 can give Print Screen back: Settings › Accessibility ›
Keyboard › "Use the Print screen key to open screen capture", off.

**AltGr.** On keyboards with AltGr (most European layouts), AltGr+key
types its character (`@`, `\`, `{`, `€`…) as it does in other programs;
it is never read as a Ctrl+Alt binding.

## Where things live

| What | Windows | Linux |
|---|---|---|
| A user's sessions, keymaps and known hosts | `%APPDATA%\Cherminal\` | `~/.config/cherminal/` |
| Session logs | `%LOCALAPPDATA%\Cherminal\Logs\` | `~/.local/state/cherminal/logs/` |
| Shared sessions and keymaps | `%ProgramData%\Cherminal\` | `/etc/xdg/cherminal/` |
| Site policy file | `%ProgramData%\Cherminal\policy.toml` | `/etc/cherminal/policy.toml` |
| Trusted SSH host keys | `%ProgramData%\ssh\ssh_known_hosts` | `/etc/ssh/ssh_known_hosts` |
| Audit log | Application event log, source `Cherminal` | syslog / journald, tag `cherminal` |

`%APPDATA%` is usually `C:\Users\<name>\AppData\Roaming` (it follows
roaming profiles), `%LOCALAPPDATA%` `C:\Users\<name>\AppData\Local` and
`%ProgramData%` `C:\ProgramData`. To move a user's sessions from Linux,
copy the contents of `~/.config/cherminal` into `%APPDATA%\Cherminal`, or
export them (`cherminal --export all.cherminal`) and import the file.
`%XDG_CONFIG_HOME%`, `%XDG_STATE_HOME%`, `%XDG_CONFIG_DIRS%` (folders
separated by `;`) and `%CHERMINAL_SITE_DIR%` still apply when they are set.

The installer creates `%ProgramData%\Cherminal` so that only
administrators can change it; everyone else can read it. With the portable
zip, create the folder yourself and set the same permissions before putting
a policy there, because any user can create folders in `C:\ProgramData`.

**Audit log.** With the policy's `audit_log = true`, each connection event
is an entry in Windows Logs › Application with source `Cherminal`: event 1
for a connection event, 2 (a warning) for a failure. Read them with:

```powershell
Get-WinEvent -FilterHashtable @{LogName='Application'; ProviderName='Cherminal'} -MaxEvents 20
```

**Local shell.** A local session runs PowerShell 7 (`pwsh`) when it is
installed, else Windows PowerShell, on a Windows pseudo-console. Set a
session's command to run something else: `cmd.exe`, `wsl.exe`, or
`"C:\Program Files\Git\bin\bash.exe" --login -i`. Send Break does nothing in
a local session on Windows.

**Serial ports** are named `COM1`, `COM2`…; the session editor suggests
the ones it finds (Device Manager › Ports shows which is which).

**Printing** uses the printers set up in Windows. Print screen and 3287
printer sessions print through Qt; host passthrough jobs go to the
session's printer (or the default one) untouched, as raw data through the
Windows print spooler, like `lp -o raw` on Linux.

## Building

On Windows with PowerShell 7, Python 3.11 or later and the .NET SDK:

```powershell
packaging\build-windows.ps1
```

It builds the app folder with PyInstaller, checks that it starts, and
writes `dist\Cherminal-<version>-windows-x64.msi` (with the WiX Toolset,
which it installs as a .NET tool if needed) and `.zip`. The `windows`
GitHub workflow runs it for every pull request, installs and uninstalls
the `.msi` to check it, and attaches both files to tagged releases.

## Signing

These builds are unsigned. Signing is planned through the
[SignPath Foundation](https://signpath.org/), which signs open-source
projects' releases for free once a project has unsigned releases out:
SignPath signs the files the `windows` workflow builds, after a maintainer
approves each release.
