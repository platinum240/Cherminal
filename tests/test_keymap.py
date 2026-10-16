import pytest

from cherminal.keymap import Keymap, format_notation, normalize_key, parse_notation


def test_normalize():
    assert normalize_key("shift+ctrl+f1") == "Ctrl+Shift+F1"
    assert normalize_key("app:up") == "app:Up"
    assert normalize_key("ctrl+c") == "Ctrl+C"
    assert normalize_key("Meta+x") == "Alt+X"
    with pytest.raises(ValueError):
        normalize_key("Hyper+F1")
    with pytest.raises(ValueError):
        normalize_key("F99")


def test_notation_roundtrip():
    raw = r"\e[15~^A@\r\x9b\\\^"
    data = parse_notation(raw)
    assert data == "\x1b[15~\x01@\r\x9b\\^"
    assert parse_notation(format_notation(data)) == data
    assert parse_notation("^?") == "\x7f"


def test_vt220_modes():
    km = Keymap.builtin("vt220")
    assert km.lookup("Up").value == "\x1b[A"
    assert km.lookup("Up", app_cursor=True).value == "\x1bOA"
    assert km.lookup("Keypad5") is None
    assert km.lookup("Keypad5", app_keypad=True).value == "\x1bOu"
    assert km.lookup("F6").value == "\x1b[17~"
    assert km.lookup("Shift+F3").value == "\x1b[25~"   # F13


def test_wyse_and_sco():
    wy = Keymap.builtin("wyse")
    assert wy.lookup("F1").value == "\x01@\r"
    assert wy.lookup("Shift+F16").value == "\x01o\r"
    sco = Keymap.builtin("ansi")
    assert sco.lookup("F1").value == "\x1b[M"
    assert sco.lookup("Shift+F1").value == "\x1b[Y"
    assert sco.lookup("Ctrl+Shift+F7").value == "\x1b[\\"


def test_overrides_and_actions():
    km = Keymap.builtin("vt220")
    km.update({"backspace": "^H", "ctrl+shift+v": "action:paste", "F1": ""})
    assert km.lookup("Backspace").value == "\b"
    b = km.lookup("Ctrl+Shift+V")
    assert (b.kind, b.value) == ("action", "paste")
    assert km.lookup("F1") is None
    with pytest.raises(ValueError):
        km.update({"F2": r"\q"})
