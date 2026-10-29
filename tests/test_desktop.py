import os

from cherminal import __main__ as cli
from cherminal import desktop, system


def test_install_desktop_entry(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(system, "IS_MAC", False)       # a Linux desktop
    monkeypatch.setattr(system, "IS_WINDOWS", False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "system"))
    monkeypatch.setenv("APPIMAGE", "/opt/apps/Cherminal 0.8.AppImage")
    assert not desktop.entry_installed()
    assert cli.main(["--install-desktop"]) == 0
    entry = tmp_path / "share/applications/cherminal.desktop"
    assert f"installed {entry}" in capsys.readouterr().out
    text = entry.read_text()
    assert 'Exec="/opt/apps/Cherminal 0.8.AppImage" %U' in text and "Icon=cherminal" in text
    assert (tmp_path / "share/icons/hicolor/256x256/apps/cherminal.png").stat().st_size > 1000
    assert (tmp_path / "share/icons/hicolor/scalable/apps/cherminal.svg").exists()
    assert desktop.entry_installed()


def test_system_wide_entry_counts(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("XDG_DATA_DIRS", os.pathsep.join([f"{tmp_path}/a", f"{tmp_path}/b"]))
    (tmp_path / "b/applications").mkdir(parents=True)
    (tmp_path / "b/applications/cherminal.desktop").write_text("[Desktop Entry]\n")
    assert desktop.entry_installed()
