"""Windows behaviour, checked on any system by switching the platform checks on."""

import os
import sys
import types
from pathlib import Path

import pytest

from cherminal import sessionlog, system
from cherminal.config import SessionProfile
from cherminal.keymap import Keymap
from cherminal.policy import Policy
from cherminal.transport import conpty, from_profile, local

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


PROGRAM_DATA = system.program_data


@pytest.fixture
def windows(monkeypatch, tmp_path):
    """Pretend to be Windows with its folders under tmp_path."""
    monkeypatch.setattr(system, "IS_MAC", False)
    monkeypatch.setattr(system, "IS_WINDOWS", True)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setattr(system, "program_data", lambda: tmp_path / "ProgramData")
    for name in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CONFIG_DIRS"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


# ------------------------------------------------------------------ folders

def test_windows_folders(windows):
    assert system.config_dir() == windows / "Roaming/Cherminal"
    assert system.log_dir() == windows / "Local/Cherminal/Logs"
    assert system.site_config_dirs() == [windows / "ProgramData/Cherminal"]
    assert system.policy_path() == windows / "ProgramData/Cherminal/policy.toml"
    assert system.system_known_hosts() == windows / "ProgramData/ssh/ssh_known_hosts"
    assert system.managed_prefs_paths("username") == []


def test_windows_folders_without_variables(windows, monkeypatch):
    for name in ("APPDATA", "LOCALAPPDATA"):
        monkeypatch.delenv(name)
    monkeypatch.setenv("HOME", str(windows))
    monkeypatch.setenv("USERPROFILE", str(windows))
    assert system.config_dir() == windows / "AppData/Roaming/Cherminal"
    assert system.log_dir() == windows / "AppData/Local/Cherminal/Logs"


def test_policy_folder_is_not_the_users_to_move(monkeypatch, tmp_path):
    monkeypatch.setenv("ProgramData", str(tmp_path))
    if sys.platform == "win32":
        # Windows itself says where ProgramData is; the variable doesn't count.
        assert PROGRAM_DATA() != tmp_path
        assert PROGRAM_DATA().is_dir()
    monkeypatch.delenv("ProgramData")
    assert PROGRAM_DATA() == Path(r"C:\ProgramData")


def test_xdg_variables_still_win_on_windows(windows, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(windows / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(windows / "state"))
    monkeypatch.setenv("XDG_CONFIG_DIRS", os.pathsep.join([str(windows / "a"), str(windows / "b")]))
    assert system.config_dir() == windows / "cfg/cherminal"
    assert system.log_dir() == windows / "state/cherminal/logs"
    assert system.site_config_dirs() == [windows / "a/cherminal", windows / "b/cherminal"]


def test_windows_defaults(windows):
    assert system.name() == "Windows"
    assert system.font_family("Monospace") == system.font_family("") == "Consolas"
    assert system.font_family("Courier New") == "Courier New"
    assert SessionProfile().serial_device == "COM1"
    assert "serial_device" not in SessionProfile().to_dict()


def test_install_desktop_not_needed(windows, capsys):
    from cherminal.__main__ import main
    assert main(["--install-desktop"]) == 0
    assert "Start menu" in capsys.readouterr().err


# ------------------------------------------------------------- local shell

def test_windows_shell(windows, monkeypatch):
    monkeypatch.setattr(local.shutil, "which", lambda name: name == "powershell.exe")
    assert local.login_shell() == ["powershell.exe"]
    monkeypatch.setattr(local.shutil, "which", lambda name: True)
    assert local.login_shell() == ["pwsh.exe"]
    monkeypatch.setattr(local.shutil, "which", lambda name: None)
    monkeypatch.setenv("COMSPEC", r"C:\Windows\system32\cmd.exe")
    assert local.login_shell() == [r"C:\Windows\system32\cmd.exe"]


def test_split_command_keeps_windows_paths():
    assert conpty.split_command(r'"C:\Program Files\Git\bin\bash.exe" --login -i') == [
        r"C:\Program Files\Git\bin\bash.exe", "--login", "-i"]
    assert conpty.split_command(r"C:\tools\plink.exe host") == [r"C:\tools\plink.exe", "host"]


class FakePty:
    """Stands in for pywinpty's PtyProcess."""

    def __init__(self, argv, env, dimensions):
        self.argv, self.env, self.size = argv, env, dimensions
        self.output = ["C:\\> ", "é"]
        self.input = []
        self.closed = False

    @classmethod
    def spawn(cls, argv, env=None, dimensions=(24, 80)):
        cls.last = cls(argv, env, dimensions)
        return cls.last

    def read(self, size):
        if not self.output:
            raise EOFError("Pty is closed")
        return self.output.pop(0)

    def write(self, text):
        self.input.append(text)

    def setwinsize(self, rows, cols):
        self.size = (rows, cols)

    def close(self, force=False):
        self.closed = True


def test_conpty_transport(windows, monkeypatch):
    monkeypatch.setitem(sys.modules, "winpty", types.SimpleNamespace(PtyProcess=FakePty))
    t = from_profile(SessionProfile(transport="local", emulation="vt220",
                                    command="cmd.exe /k echo hi"))
    assert isinstance(t, conpty.ConPtyTransport)
    t.cols, t.rows = 100, 30
    t._open()
    proc = FakePty.last
    assert proc.argv == ["cmd.exe", "/k", "echo", "hi"]
    assert proc.size == (30, 100) and proc.env["TERM"] == "vt220"
    assert t._read() == b"C:\\> "
    assert t._read() == "é".encode()
    assert t._read() == b""                     # the shell exited
    t.write("dir\r".encode())
    assert proc.input == ["dir\r"]
    t.resize(132, 43)
    assert proc.size == (43, 132)
    t.close()
    assert proc.closed and t.proc is None


# ------------------------------------------------------------------ audit log

def test_audit_goes_to_the_event_log(windows, monkeypatch):
    events = []
    monkeypatch.setattr(sessionlog, "_windows_event", lambda msg, failed: events.append((msg, failed)))
    monkeypatch.setattr(sessionlog.policy, "current", lambda: Policy(audit_log=True))
    profile = SessionProfile(name="Payroll", transport="telnet", host="mvs")
    sessionlog.audit("connected", profile)
    sessionlog.audit("failed", profile, "refused", failed=True)
    assert "session='Payroll' transport=telnet host=mvs:23 event=connected" in events[0][0]
    assert events[0][1] is False and events[1][1] is True


# ------------------------------------------------------------------ keymaps

def test_windows_keymap_extras():
    linux = Keymap.builtin("ibm3270", mac=False, windows=False)
    win = Keymap.builtin("ibm3270", mac=False, windows=True)
    assert linux.lookup("Ctrl+Break") is None
    assert win.lookup("Ctrl+Break").value == "clear"
    assert win.lookup("Pause").value == "clear"
    km = Keymap.builtin("ibm5250", mac=False, windows=True)
    assert km.lookup("Ctrl+P").value == "print"
    assert km.lookup("Shift+Pause").value == "sysreq"
    assert km.lookup("Ctrl+Break").value == "clear"
    assert (Keymap.builtin("vt220", windows=True).bindings
            == Keymap.builtin("vt220", windows=False).bindings)


# ------------------------------------------------------------------ keyboard

QtGui = pytest.importorskip("PyQt6.QtGui")
from PyQt6.QtCore import QEvent, Qt  # noqa: E402

from cherminal.gui.keys import key_name  # noqa: E402

K, M = Qt.Key, Qt.KeyboardModifier
CTRL_ALT = M.ControlModifier | M.AltModifier


def press(key, mods=M.NoModifier, text=""):
    return QtGui.QKeyEvent(QEvent.Type.KeyPress, key, mods, text)


def win_key(event):
    return key_name(event, mac=False, windows=True)


def test_altgr_types_characters():
    # German layout: AltGr+Q types @, AltGr+ß types a backslash.
    assert win_key(press(K.Key_At, CTRL_ALT, "@")) == ("", "@")
    assert win_key(press(K.Key_Backslash, CTRL_ALT, "\\")) == ("", "\\")
    assert win_key(press(K.Key_E, CTRL_ALT, "€")) == ("", "€")
    # On Linux the same event is still a Ctrl+Alt key.
    assert key_name(press(K.Key_At, CTRL_ALT, "@"), mac=False, windows=False)[0] == "Ctrl+Alt+@"


def test_real_ctrl_alt_keys_still_work():
    assert win_key(press(K.Key_F1, CTRL_ALT))[0] == "Ctrl+Alt+F1"
    assert win_key(press(K.Key_A, CTRL_ALT, ""))[0] == "Ctrl+Alt+A"
    assert win_key(press(K.Key_C, M.ControlModifier, "\x03")) == ("Ctrl+C", "\x03")
    assert win_key(press(K.Key_F1, M.AltModifier))[0] == "Alt+F1"
