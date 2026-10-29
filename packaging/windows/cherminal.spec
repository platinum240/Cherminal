# PyInstaller spec for Cherminal on Windows; run through packaging/build-windows.ps1.
#
# One folder with two programs sharing the bundled Python and Qt:
# Cherminal.exe, the app (no console window), and cherminal-cli.exe, the same
# program as a console app for the command line options (--version, --list,
# --check-policy, keycapture), which print nothing from a windowed program.
import os
import re

from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct,
                                                 StringTable, VarFileInfo, VarStruct,
                                                 VSVersionInfo)

root = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
version = re.search(r'__version__ = "(.*)"',
                    open(os.path.join(root, "cherminal", "__init__.py")).read()).group(1)
numbers = tuple(int(n) for n in re.findall(r"\d+", version)[:3]) + (0,)
icon = os.path.join(SPECPATH, "cherminal.ico")


def version_file(name: str, description: str) -> str:
    """A Windows version resource, so Explorer and Intune show what it is."""
    info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[StringFileInfo([StringTable("040904B0", [
                  StringStruct("CompanyName", "Cherminal"),
                  StringStruct("FileDescription", description),
                  StringStruct("FileVersion", version),
                  StringStruct("InternalName", name),
                  StringStruct("LegalCopyright", "Apache License 2.0"),
                  StringStruct("OriginalFilename", f"{name}.exe"),
                  StringStruct("ProductName", "Cherminal"),
                  StringStruct("ProductVersion", version)])]),
              VarFileInfo([VarStruct("Translation", [0x0409, 1200])])])
    os.makedirs(workpath, exist_ok=True)
    path = os.path.join(workpath, f"{name}-version.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(info))
    return path


a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[root],
    datas=collect_data_files("cherminal"),
    hiddenimports=["cherminal.tools.keycapture", "cherminal.transport.conpty",
                   "serial.tools.list_ports", "winpty"],
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Cherminal", console=False,
          icon=icon, version=version_file("Cherminal", "Cherminal terminal emulator"))
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name="cherminal-cli", console=True,
          icon=icon, version=version_file("cherminal-cli", "Cherminal command line"))
coll = COLLECT(gui, cli, a.binaries, a.datas, name="Cherminal")
