# Cherminal on macOS

Cherminal runs on macOS 12 (Monterey) and later, on Apple Silicon and Intel
Macs, with the same emulations, connections, key mapping, saved sessions,
printing and site policy as on Linux. This page covers what is different
on a Mac: the keyboard, where files live, managing it with Jamf or another
MDM, and building, signing and notarizing the app. Everything else is in
the [user guide](USER.md) and the [administrator guide](ADMIN.md).

## Installing

Each release has two downloads per architecture (`arm64` for Apple
Silicon, `x86_64` for Intel):

- `Cherminal-<version>-macos-<arch>.dmg`: open it and drag Cherminal to
  Applications.
- `Cherminal-<version>-macos-<arch>.pkg`: installs `Cherminal.app` into
  `/Applications`. This is the one to deploy from Jamf.

The app carries its own Python and Qt; nothing else is needed. Until the
app is signed and notarized (see below), a copy downloaded with a browser
won't open the first time: Control-click it in Finder, choose Open, then
Open again (on macOS 15, allow it in System Settings › Privacy & Security).
Copies installed by Jamf aren't marked as downloaded, so they open
normally.

The command line options all work through the app's executable:

```sh
/Applications/Cherminal.app/Contents/MacOS/Cherminal --version
/Applications/Cherminal.app/Contents/MacOS/Cherminal --ssh me@server -e vt220
/Applications/Cherminal.app/Contents/MacOS/Cherminal keycapture --name mykeys
```

A pip install (`pip install .` on Python 3.11 or later) works too and gives
the `cherminal` and `cherminal-keycapture` commands.

**Local network.** On macOS 15 and later the first connection to a host on
the local network (a mainframe or IBM i on the LAN, say) asks the user to
allow Cherminal to find devices on the local network. Hosts reached through
a router or VPN don't ask. MDM can't approve this ahead of time; users
answer it once.

## The keyboard

| Mac key | In a session |
|---|---|
| Control | Ctrl: control codes (Ctrl+C sends ^C) and every `Ctrl+` binding |
| Command (⌘) | The app's own shortcuts only; never sent to the host |
| Option (⌥) | Alt, or typing characters, as the session's **Option key** setting says |
| fn+Delete | Delete (forward) |
| fn+Up/Down/Left/Right | Page Up, Page Down, Home, End |
| fn+Return | Keypad Enter (Field Exit in 5250 sessions) |
| Help (extended keyboards) | Insert |
| Clear (keypad) | Clear in 3270 and 5250 sessions |

**Menu shortcuts** are the usual Mac ones: ⌘C copy, ⌘V paste, ⌘F search,
⌘P print screen, ⌘T local shell, ⌘N quick connect, ⌘O sessions, ⌘W close
tab, ⌘Q quit. (On Linux they are Ctrl+Shift+letter, to keep Ctrl free for
the host; on a Mac, Command already is.)

**Option key** (session editor, Keyboard tab). Mac keyboards type accented
characters with Option (Option+E then E types é). Host applications
often want Alt instead: Alt+F1 is PA1 on a 3270, and Unix programs read
Alt+letter as Esc followed by the letter.

- *Left Option is Alt, right Option types characters* (the default):
  both work, one on each side.
- *Both Option keys are Alt*: for sessions where nobody types accented
  characters.
- *Option types characters*: the normal Mac behaviour; no Alt at all.

**Keys a Mac keyboard doesn't have.** PC keyboards have Insert, Pause,
Print Screen and SysReq, and the 3270 and 5250 layouts use them. On a Mac
the built-in layouts add:

| Function | 3270 sessions | 5250 sessions |
|---|---|---|
| Insert mode | Help, or Ctrl+I | Help, or Ctrl+I |
| Clear | Clear, or Ctrl+Esc | Clear |
| Attention | | Shift+Esc (as on Linux) |
| System Request | | Ctrl+Esc |
| Print | ⌘P (Print screen) | Ctrl+P (host print) |
| Field+ / Field− | | Ctrl+= / Ctrl+− (keypad + and − too) |
| Reset | Esc | Esc |
| PF13–PF24 / F13–F24 | Shift+F1–F12 | Shift+F1–F12 |

On a laptop, F1–F12 need fn unless *Use F1, F2, etc. keys as standard
function keys* is on in System Settings › Keyboard. Turn it on for
mainframe users; the Jamf section below shows how to set it for them.

Session files, keymaps and bundles are the same on Linux and macOS, so a
keymap captured with `cherminal-keycapture` works on both. Key names stay
`Ctrl`, `Alt` and `Shift`; on a Mac they mean Control, Option (as Alt) and
Shift.

## Where things live

| What | macOS | Linux |
|---|---|---|
| A user's sessions, keymaps and known hosts | `~/Library/Application Support/Cherminal/` | `~/.config/cherminal/` |
| Session logs | `~/Library/Logs/Cherminal/` | `~/.local/state/cherminal/logs/` |
| Shared sessions and keymaps | `/Library/Application Support/Cherminal/` | `/etc/xdg/cherminal/` |
| Site policy file | `/Library/Application Support/Cherminal/policy.toml` | `/etc/cherminal/policy.toml` |
| Managed preferences | domain `io.github.platinum240.cherminal` | (none) |
| Trusted SSH host keys | `/etc/ssh/ssh_known_hosts` | `/etc/ssh/ssh_known_hosts` |
| Audit log | unified log, process `Cherminal` | syslog / journald, tag `cherminal` |

To move a user's sessions from Linux, copy `~/.config/cherminal` to the
Mac as it is: Cherminal uses it while
`~/Library/Application Support/Cherminal` doesn't exist. Or export them
on Linux (`cherminal --export all.cherminal`) and import the file on the
Mac. `$XDG_CONFIG_HOME`, `$XDG_STATE_HOME`, `$XDG_CONFIG_DIRS` and
`$CHERMINAL_SITE_DIR` still apply on a Mac when they are set.

Session logs show up in Console.app under Log Reports. Read the audit log
(policy `audit_log = true`) with:

```sh
log show --last 1d --predicate 'process == "Cherminal"' --info
```

**Serial ports** are named `/dev/cu.usbserial-…` or `/dev/cu.usbmodem…`;
the session editor suggests the ones it finds. Some USB-serial adapters
need their maker's driver.

**Printing** goes through the Mac's own printing system (CUPS), as on
Linux: printers added in System Settings show up in Print screen and can be
named in a session's Printing tab; host passthrough and 3287 printer
sessions use `lp` as on Linux.

## Managing Cherminal with Jamf (or another MDM)

**Deploying.** Upload the `.pkg` to Jamf Pro (Settings › Computer
management › Packages) and add it to a policy. It installs
`Cherminal.app` in `/Applications`. Use the build for the Macs' processor
(`arm64` or `x86_64`), or scope one policy per architecture.

**The site policy as a configuration profile.** Every setting in the
[site policy](ADMIN.md#4-the-site-policy) can come from managed
preferences instead of a file:

1. Start from `packaging/macos/policy.plist.example`, keep the settings you
   want to enforce, and check it:
   `/Applications/Cherminal.app/Contents/MacOS/Cherminal --check-policy policy.plist`.
2. In Jamf Pro: Configuration Profiles › New › Application & Custom
   Settings › Upload. Preference domain `io.github.platinum240.cherminal`;
   upload the file.
3. Scope it to computers (or users) as usual.

macOS writes the profile to `/Library/Managed Preferences/`, where users
can't change it. When there is also a `policy.toml`, the profile's
settings win; a profile scoped to a user wins over one for the whole
computer. A profile with a mistake in it stops Cherminal starting, as a
broken policy file does, so check the file before uploading it.

**Shared sessions and keymaps.** Put `*.cherminal` bundles, or `sessions/`
and `keymaps/` folders, in `/Library/Application Support/Cherminal/` with a
Jamf package or script, as described in
[sharing sessions](ADMIN.md#3-sharing-sessions-and-keymaps).

**Function keys.** For 3270 and 5250 users on laptops, a configuration
profile with the `com.apple.keyboard.fnState` key set to true in the
`.GlobalPreferences` domain makes F1–F12 work without fn (users may need
to log out and back in once).

## Building the app

On a Mac with Python 3.11 or later and the Xcode command line tools:

```sh
packaging/build-macos.sh
```

It builds `Cherminal.app` for the Mac's own architecture with PyInstaller,
checks that it starts, and writes `dist/Cherminal-<version>-macos-<arch>.dmg`
and `.pkg`. The `macos` GitHub workflow runs it on an Apple Silicon and an
Intel runner for every pull request and attaches both builds to tagged
releases. These builds are unsigned.

## Signing and notarizing

Without signing and notarization, Gatekeeper blocks the first open of a
downloaded copy (above). Signing needs an Apple
Developer Program membership and two certificates from it:

- **Developer ID Application**, to sign the app and the disk image.
- **Developer ID Installer**, to sign the `.pkg`.

Then, on the Mac that builds:

1. Install both certificates in the login keychain (Xcode › Settings ›
   Accounts, or download them from developer.apple.com and open them).
   `security find-identity -v` lists their exact names.
2. Store notarization credentials once, with an app-specific password from
   account.apple.com:

   ```sh
   xcrun notarytool store-credentials cherminal-notary \
       --apple-id you@example.com --team-id TEAMID --password app-specific-password
   ```

3. Build with the identities and the profile set:

   ```sh
   CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" \
   INSTALLER_IDENTITY="Developer ID Installer: Your Name (TEAMID)" \
   NOTARY_PROFILE=cherminal-notary \
   packaging/build-macos.sh
   ```

   The script signs the app with the hardened runtime and
   `packaging/macos/entitlements.plist`, signs the disk image and package,
   sends both to Apple's notary service, waits, and staples the tickets.

4. Check the results:

   ```sh
   spctl --assess --type execute -vv build/macos/dist/Cherminal.app
   spctl --assess --type install -vv dist/Cherminal-*-macos-*.pkg
   xcrun stapler validate dist/Cherminal-*-macos-*.dmg
   ```

To sign in GitHub Actions instead, import the two certificates (exported as
a `.p12`) into a temporary keychain from repository secrets, run
`xcrun notarytool store-credentials` there with an App Store Connect API
key, and set the same three variables for the build step.

The entitlements allow what the embedded Python needs under the hardened
runtime (executable memory for `ctypes` and loading its own extension
modules). If notarization reports a problem, `xcrun notarytool log <id>
--keychain-profile cherminal-notary` shows the details.

## Not yet on macOS

- Opening a `.cherminal` bundle by double-clicking it in Finder. Import it
  from the session manager or with `--import` instead.
- Middle-click paste of the last selection (an X11 feature): select, ⌘C,
  ⌘V instead.
- `--install-desktop` does nothing on a Mac; the app goes in Applications.
