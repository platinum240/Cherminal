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


def test_keys_follow_application_mode(tmp_path):
    s, t = make(tmp_path)
    s.key("Up")
    s.feed(b"\x1b[?1h")
    s.key("Up")
    assert bytes(t.sent) == b"\x1b[A\x1bOA"


def test_unmapped_text_and_alt(tmp_path):
    s, t = make(tmp_path)
    assert s.key("A", "a")
    assert s.key("Alt+X", "x")
    assert not s.key("F24")
    assert bytes(t.sent) == b"a\x1bx"


def test_emulator_replies_go_to_host(tmp_path):
    s, t = make(tmp_path)
    s.feed(b"\x1b[6n")
    assert bytes(t.sent) == b"\x1b[1;1R"


def test_macros_and_actions(tmp_path):
    s, t = make(tmp_path, macros={"login": "operator\\r", "loop": "action:macro:loop"},
                keys={"F5": "action:macro:login", "F6": "action:macro:loop"})
    actions = []
    s.on_action = actions.append
    s.key("F5")
    s.key("F6")              # must terminate
    s.key("Ctrl+Shift+C")
    assert bytes(t.sent) == b"operator\r"
    assert actions == ["copy"]


def test_paste_and_local_echo(tmp_path):
    s, t = make(tmp_path, local_echo=True)
    s.paste("a\nb")
    assert bytes(t.sent) == b"a\rb"
    assert s.screen.line_text(0) == "b"   # CR returned to column 0


def test_wyse_profile_uses_wyse_keys(tmp_path):
    s, t = make(tmp_path, emulation="wyse60")
    s.key("F1")
    s.key("Up")
    assert bytes(t.sent) == b"\x01@\r\x0b"
