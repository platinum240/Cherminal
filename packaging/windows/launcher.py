"""Entry point of Cherminal.exe and cherminal-cli.exe: `keycapture ...` runs
the key capture tool, anything else runs Cherminal, as the AppImage does."""

import sys

if len(sys.argv) > 1 and sys.argv[1] in ("keycapture", "cherminal-keycapture"):
    del sys.argv[1]
    from cherminal.tools.keycapture import main
else:
    from cherminal.__main__ import main

sys.exit(main())
