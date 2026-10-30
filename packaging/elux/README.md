# Cherminal for eLux thin clients

eLux installs software as EPM packages (each made of one or more FPM parts)
that Scout and ELIAS deploy to the clients. Cherminal's package holds the
unpacked AppImage in `/opt/cherminal`, so clients need no FUSE, Python or Qt.

## Build

1. Build or download the AppImage (`packaging/build-appimage.sh`, or the
   `appimage` workflow / release). The same workflow also produces
   `cherminal-elux-<version>.tar.gz`, the package tree from step 2.
2. Make the package tree:

   ```sh
   packaging/elux/build-epm.sh dist/Cherminal-<version>-x86_64.AppImage
   ```

3. Package it with Unicon's `epkg` tool, which comes with the eLux SDK VM.
   If the script runs inside the SDK VM it calls `epkg` itself; otherwise
   copy `dist/cherminal-elux-<version>.tar.gz` there, unpack it, and in the
   unpacked folder run:

   ```sh
   epkg Build --container elux7 --releaseType test      # or: --releaseType release
   ```

   The `.epm` and `.fpm` files appear in `output/container/`. Import them
   into ELIAS and assign them to your clients' image in Scout.

`epkg` signs packages with the key and certificate set in
`/etc/epkg/settings.ini` (`[Signing]`). Clients only install packages whose
signing certificate is in `/setup/cacerts/`, so deploy that certificate
from Scout first.

The package metadata is in `ebkepm.in` (application) and `control`. They
follow Unicon's epkg documentation but have not yet been built with a real
`epkg`; if `epkg Build` rejects a field, fix it there or in the eLux Builder
Kit, which opens the same tree. The target is eLux 7 (`containers=2048`);
for eLux RP6 64-bit use `containers=1024`.

## Size

The package tree is about 155 MB unpacked (`build-epm.sh` prints the exact
figure); the `.fpm` is compressed and smaller. Most of it is Qt (with ICU,
about 40 MB, which Qt needs for text) and Python. `packaging/slim-appdir.sh`
leaves out the Qt modules, plugins and Python parts Cherminal never loads;
before 0.13.2 the package was about 340 MB.

## If the package won't install

Check these in Scout before digging through logs:

- **Flash space.** The image (firmware plus every package assigned) has to
  fit the client's flash, with room to download the update. Compare the
  device's flash size in Scout with the image size ELIAS shows.
- **eLux version.** `containers=2048` targets eLux 7; a client on eLux RP6
  ignores or rejects the package. Use `containers=1024` for RP6 64-bit
  (in `ebkepm.in` and `--container` for `epkg`).
- **Architecture.** The package is `amd64` only (64-bit x86 clients).
- **Signature.** `--releaseType test` packages are signed with the SDK's
  test key; the client must have the signing certificate in
  `/setup/cacerts/` (deploy it from Scout), or the package is refused.
- **Libraries on the client.** Cherminal needs X11, fontconfig, freetype,
  EGL/GL, D-Bus and glibc 2.28 or later from eLux itself. With
  `checkMissingFiles=true`, files the package needs but doesn't have are
  reported, so the slimmer package also has fewer things to report.

On the client, the update and package logs are in `/var/log` (open a local
terminal if your Scout profile allows one). The easiest way to get them all
is a diagnostic file: request it from the device in Scout (Diagnostics), or
create it on the client in the Control Panel and save it to a USB stick.

## What gets installed

| Path | |
|---|---|
| `/opt/cherminal/` | the application, with its own Python and Qt |
| `/usr/bin/cherminal`, `/usr/bin/cherminal-keycapture` | commands |
| `/usr/share/applications/cherminal.desktop` and icons | menu entry |
| `/etc/cherminal/policy.toml.example` | every policy setting, commented |
| `/etc/cherminal/policy.toml` | only if you add a site policy (below) |

Shared sessions and keymaps go in `/etc/xdg/cherminal/` as on any other
Linux (see the main README's "Shared setup").

## Site policy

To lock clients down, write a policy (start from `policy.toml.example`),
check it, and save it as `packaging/elux/site/policy.toml` before step 2:

```sh
cherminal --check-policy packaging/elux/site/policy.toml
```

The script then adds a second part, `cherminal-policy`, that installs it as
`/etc/cherminal/policy.toml`. Users can't change or bypass it: Cherminal
reads only that path, and a policy with a mistake in it stops Cherminal
from starting rather than letting it run unrestricted.

To start Cherminal in limited mode from a Scout application entry without
a policy, use `cherminal --limited "Session name"` as the command.
