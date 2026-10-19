import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

from cherminal.config import ProfileStore, SessionProfile  # noqa: E402
from cherminal.gui.keyboard import DEFAULT, PLAIN, SEND, KeyboardEditor  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def editor(store, emulation="ibm3278-2", keys=None, **kw):
    p = SessionProfile(transport="telnet", host="h", emulation=emulation)
    return KeyboardEditor(store.build_keymap(p), keys or {}, store=store, **kw)


def choose(ed, data):
    ed.choice.setCurrentIndex(ed.choice.findData(data))


def test_click_key_and_pick_action(app, tmp_path):
    store = ProfileStore(tmp_path, site_roots=[])
    ed = editor(store, block_mode=True, base_name="ibm3270")
    ed.buttons["F3"].click()
    assert ed.current == "F3" and ed.default_label.text() == "PF3"
    choose(ed, "action:pf15")
    assert ed.overrides == {"F3": "action:pf15"}
    assert "PF15" in ed.buttons["F3"].text()
    choose(ed, DEFAULT)
    assert ed.overrides == {}


def test_modifier_layers_and_shifted_punctuation(app, tmp_path):
    store = ProfileStore(tmp_path, site_roots=[])
    ed = editor(store, block_mode=True)
    shift = next(b for m, b in ed.mod_buttons if m == "Shift")
    shift.setChecked(True)
    assert all(b.isChecked() for m, b in ed.mod_buttons if m == "Shift")  # both Shift keys
    ed.buttons["F1"].click()
    assert ed.current == "Shift+F1" and ed.default_label.text() == "PF13"
    ed.buttons["1"].click()
    assert ed.current == "Shift+!"                 # named as the key event names it
    ctrl = next(b for m, b in ed.mod_buttons if m == "Ctrl")
    ctrl.setChecked(True)
    assert ed.current == "Ctrl+Shift+!"            # the selection follows the layer


def test_send_text_plain_and_validation(app, tmp_path):
    store = ProfileStore(tmp_path, site_roots=[])
    ed = editor(store, emulation="vt220", keys={"F12": "^AK\\r"})
    ed.buttons["F12"].click()
    assert ed.choice.currentData() == SEND and ed.text.text() == "^AK\\r"
    ed.text.setText("\\q")                          # bad escape: not stored
    ed.text.textEdited.emit("\\q")
    assert ed.overrides["F12"] == "^AK\\r"
    ed.text.setText("\\e[24~")
    ed.text.textEdited.emit("\\e[24~")
    assert ed.overrides["F12"] == "\\e[24~"
    ed.buttons["Backspace"].click()
    choose(ed, PLAIN)
    assert ed.overrides["Backspace"] == ""         # unbound: types its character
    ed.show_key("Alt+F4")
    assert ed.current == "Alt+F4" and ed.mods == {"Ctrl": False, "Alt": True, "Shift": False}


def test_result_is_a_working_keymap(app, tmp_path):
    store = ProfileStore(tmp_path, site_roots=[])
    ed = editor(store, block_mode=True, base_name="ibm3270", macros=["logon"])
    ed.buttons["Pause"].click()
    choose(ed, "action:macro:logon")
    store.save_keymap("site-3270", ed.overrides, inherit="ibm3270")
    p = SessionProfile(transport="telnet", host="h", emulation="ibm3278-2", keymap="site-3270",
                       macros={"logon": "TSO\\r"})
    km = store.build_keymap(p)
    assert km.lookup("Pause").value == "macro:logon"
    assert km.lookup("F3").value == "pf3"          # everything else inherited
