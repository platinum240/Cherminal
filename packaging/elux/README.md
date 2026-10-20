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
