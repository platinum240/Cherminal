# PyInstaller spec for Cherminal.app; run through packaging/build-macos.sh.
import os
import re

from PyInstaller.utils.hooks import collect_data_files

root = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
version = re.search(r'__version__ = "(.*)"',
                    open(os.path.join(root, "cherminal", "__init__.py")).read()).group(1)
bundle_id = "io.github.platinum240.cherminal"     # cherminal.system.MAC_BUNDLE_ID

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[root],
    datas=collect_data_files("cherminal"),
    hiddenimports=["cherminal.tools.keycapture", "serial.tools.list_ports"],
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Cherminal",
          console=False, argv_emulation=False,
          target_arch=os.environ.get("TARGET_ARCH") or None)
coll = COLLECT(exe, a.binaries, a.datas, name="Cherminal")
app = BUNDLE(
    coll,
    name="Cherminal.app",
    icon=os.path.join(root, "build", "macos", "Cherminal.icns"),
    bundle_identifier=bundle_id,
    version=version,
    info_plist={
        "CFBundleName": "Cherminal",
        "CFBundleDisplayName": "Cherminal",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "LSMinimumSystemVersion": "12.0",
        "LSApplicationCategoryType": "public.app-category.developer-tools",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
        "NSHumanReadableCopyright": "Apache License 2.0",
        # macOS 15 and later ask before an app connects to hosts on the local
        # network (a mainframe or IBM i on the LAN); this is the reason shown.
        "NSLocalNetworkUsageDescription":
            "Cherminal connects to the hosts in your sessions, which may be on "
            "your local network.",
    },
)
