"""macOS behaviour, checked on any system by switching the platform checks on."""

import os
import plistlib
import sys
from pathlib import Path

import pytest

from cherminal import policy, system
from cherminal.config import SessionProfile
from cherminal.keymap import Keymap
from cherminal.policy import Policy, PolicyError
from cherminal.transport import local

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def mac(monkeypatch, tmp_path):
    """Pretend to be a Mac with an empty home folder and no XDG variables."""
    monkeypatch.setattr(system, "IS_MAC", True)
    monkeypatch.setattr(system, "IS_WINDOWS", False)
    monkeypatch.setenv("HOME", str(tmp_path))
    for name in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CONFIG_DIRS"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


# ------------------------------------------------------------------ folders

def test_mac_folders(mac):
    assert system.config_dir() == mac / "Library/Application Support/Cherminal"
    assert system.log_dir() == mac / "Library/Logs/Cherminal"
    assert system.site_config_dirs() == [Path("/Library/Application Support/Cherminal")]
    assert system.policy_path() == Path("/Library/Application Support/Cherminal/policy.toml")


def test_mac_uses_a_config_folder_copied_from_linux(mac):
    (mac / ".config/cherminal/sessions").mkdir(parents=True)
    assert system.config_dir() == mac / ".config/cherminal"
    (mac / "Library/Application Support/Cherminal").mkdir(parents=True)
    assert system.config_dir() == mac / "Library/Application Support/Cherminal"


def test_xdg_variables_still_win_on_mac(mac, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(mac / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(mac / "state"))
    assert system.config_dir() == mac / "cfg/cherminal"
    assert system.log_dir() == mac / "state/cherminal/logs"


def test_linux_folders_unchanged(monkeypatch, tmp_path):
    monkeypatch.setattr(system, "IS_MAC", False)
    monkeypatch.setattr(system, "IS_WINDOWS", False)
    monkeypatch.setenv("HOME", str(tmp_path))
    for name in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CONFIG_DIRS"):
        monkeypatch.delenv(name, raising=False)
    assert system.config_dir() == tmp_path / ".config/cherminal"
    assert system.log_dir() == tmp_path / ".local/state/cherminal/logs"
    assert system.site_config_dirs() == [Path("/etc/xdg/cherminal")]
    assert system.managed_prefs_paths("chad") == []


def test_fonts(monkeypatch):
    monkeypatch.setattr(system, "IS_WINDOWS", False)
    monkeypatch.setattr(system, "IS_MAC", True)
    assert system.font_family("Monospace") == system.font_family("") == "Menlo"
    assert system.font_family("Courier") == "Courier"
    monkeypatch.setattr(system, "IS_MAC", False)
    assert system.font_family("") == "Monospace"


@pytest.mark.skipif(sys.platform == "win32", reason="Unix shells")
def test_login_shell(monkeypatch):
    monkeypatch.setattr(system, "IS_WINDOWS", False)
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setattr(system, "IS_MAC", True)
    assert local.login_shell() == ["/bin/zsh", "-l"]
    monkeypatch.setattr(system, "IS_MAC", False)
    assert local.login_shell() == ["/bin/zsh"]
    monkeypatch.delenv("SHELL")
    assert local.login_shell()[0]               # from the user's account


# ------------------------------------------------------- managed preferences

def write_plist(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        plistlib.dump(data, f)
    return path


def test_managed_prefs_paths(mac):
    name = "io.github.platinum240.cherminal.plist"
    assert system.managed_prefs_paths("chad") == [
        Path("/Library/Managed Preferences") / name,
        Path("/Library/Managed Preferences/chad") / name]


def test_plist_policy(tmp_path):
    path = write_plist(tmp_path / "p.plist", {
        "limited": True, "allowed_transports": ["telnet"], "max_idle_timeout": 10,
        "PayloadUUID": "ABC", "PayloadIdentifier": "x"})
    rules = policy.read(path)
    assert rules.limited and rules.allowed_transports == ("telnet",)
    assert rules.max_idle_timeout == 10


def test_plist_mistakes_are_errors(tmp_path):
    with pytest.raises(PolicyError, match="limited must be true or false"):
        policy.read(write_plist(tmp_path / "a.plist", {"limited": "yes"}))
    with pytest.raises(PolicyError, match="unknown policy setting"):
        policy.read(write_plist(tmp_path / "b.plist", {"limted": True}))
    (tmp_path / "c.plist").write_text("not a plist")
    with pytest.raises(PolicyError, match="c.plist"):
        policy.read(tmp_path / "c.plist")
    with pytest.raises(PolicyError, match="dictionary"):
        policy.read(write_plist(tmp_path / "d.plist", ["limited"]))


def test_managed_prefs_override_file_and_user_overrides_computer(monkeypatch, tmp_path):
    toml = tmp_path / "policy.toml"
    toml.write_text('max_idle_timeout = 30\naudit_log = true\n')
    computer = write_plist(tmp_path / "mp/x.plist", {"max_idle_timeout": 10, "limited": True})
    user = write_plist(tmp_path / "mp/chad/x.plist", {"limited": False})
    monkeypatch.setattr(policy, "managed_prefs_paths", lambda: [computer, user])
    rules = policy.load(toml)
    assert rules.audit_log and rules.max_idle_timeout == 10 and not rules.limited
    assert rules.source == f"{toml}, {computer}, {user}"


def test_managed_prefs_alone(monkeypatch, tmp_path):
    prefs = write_plist(tmp_path / "x.plist", {"print_to_file": False})
    monkeypatch.setattr(policy, "managed_prefs_paths", lambda: [prefs])
    assert policy.load(tmp_path / "missing.toml") == Policy(print_to_file=False)
    monkeypatch.setattr(policy, "managed_prefs_paths", lambda: [tmp_path / "none.plist"])
    assert policy.load(tmp_path / "missing.toml") == Policy()


def test_check_policy_reads_a_plist(tmp_path, capsys):
    from cherminal.__main__ import main
    path = write_plist(tmp_path / "jamf.plist", {"require_tls": True})
    assert main(["--check-policy", str(path)]) == 0
    assert "require_tls = True" in capsys.readouterr().out


# ------------------------------------------------------------------ keymaps

def test_mac_keymap_extras():
    linux = Keymap.builtin("ibm3270", mac=False)
    mac = Keymap.builtin("ibm3270", mac=True)
    assert linux.lookup("Clear") is None
    assert mac.lookup("Clear").value == mac.lookup("Ctrl+Escape").value == "clear"
    assert mac.lookup("Ctrl+I").value == "insert"
    assert mac.lookup("Pause").value == "clear"            # PC keyboards still work
    km = Keymap.builtin("ibm5250", mac=True)
    assert km.lookup("Ctrl+Escape").value == "sysreq"
    assert km.lookup("Ctrl+=").value == "field-plus"
    assert Keymap.builtin("vt220", mac=True).bindings == Keymap.builtin("vt220", mac=False).bindings


def test_option_key_setting():
    assert SessionProfile().option_key == "left-alt"
    assert SessionProfile(option_key="text").option_key == "text"
    with pytest.raises(ValueError, match="option_key"):
        SessionProfile(option_key="meta")


# ------------------------------------------------------------------ keyboard

QtGui = pytest.importorskip("PyQt6.QtGui")
from PyQt6.QtCore import QEvent, Qt  # noqa: E402

from cherminal.gui.app import menu_shortcut  # noqa: E402
from cherminal.gui.keys import key_name  # noqa: E402

K, M = Qt.Key, Qt.KeyboardModifier
LEFT_OPTION, RIGHT_OPTION = 0x20, 0x40


def press(key, mods=M.NoModifier, text="", native=0):
    return QtGui.QKeyEvent(QEvent.Type.KeyPress, key, mods, 0, 0, native, text)


def mac_key(event, option_key="left-alt"):
    return key_name(event, option_key, mac=True)


def test_mac_control_key_sends_control_codes():
    # Qt on macOS: the Control key is Meta, Command is Control.
    assert mac_key(press(K.Key_C, M.MetaModifier, "\x03")) == ("Ctrl+C", "\x03")
    assert mac_key(press(K.Key_C, M.ControlModifier, "c")) is None
    assert mac_key(press(K.Key_F1, M.MetaModifier | M.ShiftModifier))[0] == "Ctrl+Shift+F1"


def test_mac_option_as_alt():
    left = press(K.Key_E, M.AltModifier, "´", LEFT_OPTION)
    right = press(K.Key_E, M.AltModifier, "é", RIGHT_OPTION)
    assert mac_key(left) == ("Alt+E", "e")
    assert mac_key(right) == ("", "é")                  # right Option types é
    assert mac_key(right, "alt") == ("Alt+E", "e")
    assert mac_key(left, "text") == ("", "´")
    shifted = press(K.Key_E, M.AltModifier | M.ShiftModifier, "", LEFT_OPTION)
    assert mac_key(shifted) == ("Alt+Shift+E", "E")
    assert mac_key(press(K.Key_F1, M.AltModifier, "", LEFT_OPTION))[0] == "Alt+F1"
    assert mac_key(press(K.Key_Left, M.AltModifier, "", RIGHT_OPTION))[0] == "Left"


def test_mac_only_keys():
    assert mac_key(press(K.Key_Help))[0] == "Insert"
    assert mac_key(press(K.Key_Clear, M.KeypadModifier))[0] == "Clear"
    assert key_name(press(K.Key_Clear), mac=False) is None


def test_linux_keys_unchanged():
    assert key_name(press(K.Key_C, M.ControlModifier, "\x03"), mac=False) == ("Ctrl+C", "\x03")
    assert key_name(press(K.Key_E, M.AltModifier, "e"), mac=False) == ("Alt+E", "e")
    assert key_name(press(K.Key_C, M.MetaModifier, "c"), mac=False) == ("C", "c")


def test_menu_shortcuts():
    assert menu_shortcut("Ctrl+Shift+W", mac=False) == "Ctrl+Shift+W"
    assert menu_shortcut("Ctrl+Shift+W", mac=True) == "Ctrl+W"         # Cmd+W
    assert menu_shortcut("mac:copy", mac=False) == ""
    assert menu_shortcut("mac:copy", mac=True) == "Ctrl+C"             # Cmd+C


def test_option_key_is_taken_before_macos_composes(monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QApplication

    from cherminal.config import ProfileStore
    from cherminal.gui.terminal import TerminalWidget
    from cherminal.session import Session
    app = QApplication.instance() or QApplication([])  # noqa: F841 (kept alive)
    monkeypatch.setattr(system, "IS_MAC", True)
    profile = SessionProfile(transport="telnet", host="127.0.0.1", emulation="xterm")
    term = TerminalWidget(Session(profile, ProfileStore(tmp_path, site_roots=[])))
    keys = []
    monkeypatch.setattr(term.session, "key", lambda name, text: keys.append((name, text)) or True)
    override = QtGui.QKeyEvent(QEvent.Type.ShortcutOverride, K.Key_B, M.AltModifier, 0, 0,
                               LEFT_OPTION, "∫")
    assert term.event(override) and override.isAccepted()
    term.keyPressEvent(QtGui.QKeyEvent(QEvent.Type.KeyPress, K.Key_B, M.AltModifier, 0, 0,
                                       LEFT_OPTION, "∫"))      # the same key again
    assert keys == [("Alt+B", "b")]
    # The right Option key still types (no override taken).
    right = QtGui.QKeyEvent(QEvent.Type.ShortcutOverride, K.Key_B, M.AltModifier, 0, 0,
                            RIGHT_OPTION, "∫")
    term.event(right)
    term.keyPressEvent(QtGui.QKeyEvent(QEvent.Type.KeyPress, K.Key_B, M.AltModifier, 0, 0,
                                       RIGHT_OPTION, "∫"))
    assert keys == [("Alt+B", "b")]


def test_mac_menu_shortcuts_in_the_window(monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QApplication

    from cherminal.config import ProfileStore
    from cherminal.gui.app import MainWindow
    app = QApplication.instance() or QApplication([])  # noqa: F841 (kept alive)
    monkeypatch.setattr(system, "IS_MAC", True)
    win = MainWindow(ProfileStore(tmp_path, site_roots=[]))
    keys = {a.text().replace("&", ""): a.shortcut().toString()
            for m in win.menuBar().actions() for a in m.menu().actions() if a.text()}
    assert keys["Close tab"] == "Ctrl+W" and keys["Copy"] == "Ctrl+C"   # Cmd on a Mac
    assert keys["Print screen…"] == "Ctrl+P"
