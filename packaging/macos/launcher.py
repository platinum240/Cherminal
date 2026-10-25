"""Entry point of Cherminal.app: `Cherminal keycapture ...` runs the key
capture tool, anything else runs Cherminal, as the AppImage does."""

import sys

# Old macOS versions pass a process serial number when Finder starts an app.
sys.argv = [a for a in sys.argv if not a.startswith("-psn_")]

if len(sys.argv) > 1 and sys.argv[1] in ("keycapture", "cherminal-keycapture"):
    del sys.argv[1]
    from cherminal.tools.keycapture import main
else:
    from cherminal.__main__ import main

sys.exit(main())
