"""SCO ANSI emulation and what the Enter keys send."""

import pytest

from cherminal import emulation
from cherminal.config import ProfileStore, SessionProfile
from cherminal.session import Session
from cherminal.transport.base import Transport


class FakeTransport(Transport):
    def __init__(self):
        super().__init__()
        self.sent = bytearray()

    def write(self, data):
        self.sent += data


def make(tmp_path, **kw):
    t = FakeTransport()
    s = Session(SessionProfile(**kw), ProfileStore(tmp_path), transport=t)
    return s, t


def press(s, t, *keys):
    t.sent.clear()
    for k in keys:
        s.key(k)
    return bytes(t.sent)


def test_scoansi_is_listed_and_ansi_still_loads(tmp_path):
    assert "scoansi" in emulation.EMULATIONS
    assert "ansi" not in emulation.EMULATIONS
    assert SessionProfile(emulation="ansi").emulation == "scoansi"
    store = ProfileStore(tmp_path)
    store.sessions_dir.mkdir(parents=True)
    (store.sessions_dir / "old.toml").write_text('name = "old"\nemulation = "ansi"\n')
    assert store.load("old").emulation == "scoansi"
    assert emulation.create("ansi", None).name == "scoansi"


def test_scoansi_identity(tmp_path):
    s, _ = make(tmp_path, emulation="scoansi")
    assert s.emulation.term_type == "scoansi"
    assert s.profile.effective_encoding == "cp437"


def test_scoansi_enter_keys_send_cr(tmp_path):
    s, t = make(tmp_path, emulation="scoansi")
    assert press(s, t, "Enter", "KeypadEnter", "Shift+Enter") == b"\r\r\r"


def test_scoansi_ignores_dec_keypad_and_cursor_modes(tmp_path):
    # A host that thinks it is talking to a VT (TERM=vt100) turns on keypad
    # application mode; on SCO ANSI keypad Enter must still be a plain CR.
    s, t = make(tmp_path, emulation="scoansi")
    s.feed(b"\x1b=\x1b[?1h\x1b[?66h")
    assert not s.emulation.app_keypad and not s.emulation.app_cursor
    assert press(s, t, "KeypadEnter", "Up", "Keypad5") == b"\r\x1b[A"


def test_vt_keypad_enter_follows_application_mode(tmp_path):
    s, t = make(tmp_path, emulation="vt220")
    assert press(s, t, "KeypadEnter") == b"\r"
    s.feed(b"\x1b=")
    assert press(s, t, "KeypadEnter") == b"\x1bOM"


@pytest.mark.parametrize("setting, sent", [("cr", b"\r"), ("crlf", b"\r\n"), ("lf", b"\n")])
def test_keypad_enter_setting_beats_application_mode(tmp_path, setting, sent):
    s, t = make(tmp_path, emulation="vt220", keypad_enter_sends=setting)
    s.feed(b"\x1b=")
    assert press(s, t, "KeypadEnter") == sent
    assert press(s, t, "Enter") == b"\r"


@pytest.mark.parametrize("emu", ["scoansi", "vt100", "wyse60"])
@pytest.mark.parametrize("setting, sent", [("cr", b"\r"), ("crlf", b"\r\n"), ("lf", b"\n")])
def test_enter_sends_setting(tmp_path, emu, setting, sent):
    s, t = make(tmp_path, emulation=emu, enter_sends=setting)
    assert press(s, t, "Enter") == sent
    assert press(s, t, "KeypadEnter") == sent
    assert press(s, t, "Shift+Enter") == sent


def test_keypad_enter_can_differ_from_enter(tmp_path):
    s, t = make(tmp_path, emulation="scoansi", enter_sends="cr", keypad_enter_sends="crlf")
    assert press(s, t, "Enter", "KeypadEnter") == b"\r\r\n"


def test_session_keys_override_enter_settings(tmp_path):
    s, t = make(tmp_path, emulation="scoansi", enter_sends="crlf",
                keys={"KeypadEnter": "\\n"})
    assert press(s, t, "Enter", "KeypadEnter") == b"\r\n\n"


def test_bad_keypad_enter_setting():
    with pytest.raises(ValueError):
        SessionProfile(keypad_enter_sends="cr-lf")


def test_line_feed_new_line_mode(tmp_path):
    # VT LNM (CSI 20 h): the host asks for CR LF from Return.
    s, t = make(tmp_path, emulation="vt220")
    s.feed(b"\x1b[20h")
    assert press(s, t, "Enter", "KeypadEnter") == b"\r\n\r\n"
    s.feed(b"\x1b[20l")
    assert press(s, t, "Enter") == b"\r"


def test_keypad_enter_setting_round_trips(tmp_path):
    store = ProfileStore(tmp_path)
    store.save(SessionProfile(name="sco", emulation="scoansi", keypad_enter_sends="cr"))
    p = store.load("sco")
    assert (p.emulation, p.keypad_enter_sends) == ("scoansi", "cr")
    assert "keypad_enter_sends" not in SessionProfile(name="x").to_dict()


@pytest.fixture(scope="module")
def app():
    QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_editor_enter_settings(app, tmp_path):
    from cherminal.gui.dialogs import SessionEditor
    ed = SessionEditor(SessionProfile(name="sco", transport="telnet", host="h",
                                      emulation="ansi", enter_sends="crlf",
                                      keypad_enter_sends="cr"),
                       ProfileStore(tmp_path, site_roots=[]))
    assert ed.emulation.currentText() == "scoansi"
    built = ed._build()
    assert (built.emulation, built.enter_sends, built.keypad_enter_sends) == \
        ("scoansi", "crlf", "cr")
    ed.keypad_enter_sends.setCurrentIndex(ed.keypad_enter_sends.findData(""))
    assert ed._build().keypad_enter_sends == ""
