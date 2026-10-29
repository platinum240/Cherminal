"""Modern view, phase 2: themes, inline field errors, clickable menus and
list rows, and wheel paging."""

import os

import pytest
from test_ibm3270 import addr, e, record
from test_ibm3270 import emu as emu3270
from test_ibm5250 import CLEAR, ESC, IC, cells, read, sf, wtd
from test_ibm5250 import emu as emu5250
from test_ibm5250 import record as record5250

from cherminal.config import ProfileStore, SessionProfile
from cherminal.emulation.base import InputField
from cherminal.emulation.choices import ListRow, find_choices, select_code

# ----------------------------------------------------------------- choices

ISPF = [" Menu  Utilities  Help", "", "                 ISPF Primary Option Menu",
        " Option ===> ",
        "", "  0  Settings      Terminal and user parameters",
        "  1  View          Display source data or listings",
        "  2  Edit          Create or change source data", "",
        " F1=Help  F3=Exit"]


def test_menu_options_need_an_option_field():
    lines = [line.ljust(80) for line in ISPF]
    command = InputField(3, 13, 60)
    found = find_choices(lines, [command])
    assert found.command == command
    assert [(o.row, o.start, o.code) for o in found.options] == [(5, 2, "0"), (6, 2, "1"),
                                                                 (7, 2, "2")]
    assert found.at(6, 20) == found.options[1] and found.at(4, 5) is None
    assert find_choices(lines, []).options == []                 # nowhere to type it


def test_ibm_i_menu_with_bare_arrow_prompt():
    lines = [line.ljust(80) for line in [
        " MAIN                     IBM i Main Menu", "", " Select one of the following:", "",
        "      1. User tasks", "      2. Office tasks", "     90. Sign off", "",
        " Selection or command", " ===> "]]
    found = find_choices(lines, [InputField(9, 6, 70)])
    assert [o.code for o in found.options] == ["1", "2", "90"]


def test_numbered_lines_without_a_prompt_are_not_a_menu():
    lines = [line.ljust(80) for line in ["  1  first", "  2  second", " Name . . "]]
    assert find_choices(lines, [InputField(2, 11, 20)]).options == []


def test_list_rows_and_their_select_code():
    lines = [line.ljust(80) for line in [
        " Type S beside an order and press Enter to view it.", "",
        "  _   SO-77120   10/24/26    3,118.40  SHIPPED",
        "  _   SO-77093   10/18/26    9,870.00  OPEN", "", " Command ===> "]]
    fields = [InputField(2, 2, 1), InputField(3, 2, 1), InputField(5, 14, 40)]
    found = find_choices(lines, fields)
    assert found.rows == [ListRow(2, 2, len(lines[2].rstrip()), fields[0]),
                          ListRow(3, 2, len(lines[3].rstrip()), fields[1])]
    assert found.select == "S"
    assert found.options == []


def test_select_code_never_picks_a_change():
    assert select_code("Type options, press Enter.\n  2=Change   4=Delete   5=Display") == "5"
    assert select_code("1=Select  2=Edit  3=Copy") == "1"
    assert select_code("Type D beside a member to delete it") == ""
    assert select_code("2=Change  4=Delete") == ""


# ------------------------------------------------------------ inline errors


NUMERIC = (b"\xf5\xc3" + b"\x11" + addr(2, 0) + b"\x1d\x60" + e("Qty") + b"\x1d\x50"
           + b"\x13" + b"\x00" * 5 + b"\x1d\x60")


def test_3270_numeric_field_hint_instead_of_beep():
    em, _, _ = emu3270()
    beeps = []
    em.on_bell = lambda: beeps.append(1)
    em.feed(record(NUMERIC))
    em.type_text("A")
    assert em.field_error is None and beeps == [1]           # classic: beep, X NUM
    em.soft_errors = True
    em.type_text("B")
    assert em.field_error == (2 * 80 + 5, "Numbers only in this field") and beeps == [1]
    em.type_text("4")
    assert em.field_error is None and em.input_fields()[0].modified


def test_5250_field_rules_show_a_hint_without_inhibiting():
    em, screen, _ = emu5250()
    em.feed(record5250(bytes([ESC, CLEAR]) + wtd(
        sf(2, 10, 0x24, 6, 0x4300) + bytes([IC, 2, 11])) + read()))
    em.soft_errors = True
    em.type_text("x")
    assert em.field_error == (80 + 10, "Numbers only in this field")
    assert not em.inhibited                                    # no Reset needed
    em.type_text("5")
    assert em.field_error is None and cells(screen, 1, 10, 11) == "5"
    em.soft_errors = False
    em.type_text("y")
    assert em.inhibited and em.field_error is None             # classic 5250


def test_5250_mandatory_entry_hint():
    em, _, sent = emu5250()
    em.feed(record5250(bytes([ESC, CLEAR]) + wtd(
        sf(2, 10, 0x24, 6, 0x4008) + bytes([IC, 2, 11])) + read()))
    em.soft_errors = True
    em.do_action("enter")
    assert em.field_error == (80 + 10, "Fill in this field before pressing Enter")
    assert not em.inhibited and sent == []


# ------------------------------------------------------------------ GUI

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


MENU = (b"\xf5\xc3"
        + b"\x11" + addr(3, 1) + b"\x1d\x60" + e("Option ===>") + b"\x1d\x40" + b"\x13"
        + b"\x00" * 40 + b"\x1d\x60"
        + b"\x11" + addr(5, 2) + e("1  View          Display source data")
        + b"\x11" + addr(6, 2) + e("2  Edit          Create or change source data")
        + b"\x11" + addr(22, 1) + e("F3=Exit  F7=Up  F8=Down"))

LIST = (b"\xf5\xc3"
        + b"\x11" + addr(1, 1) + b"\x1d\x60" + e("Type S beside an order to view it.")
        + b"".join(b"\x11" + addr(3 + i, 1) + b"\x1d\x40\x00\x1d\x60" + e(t) for i, t in
                   enumerate(["  SO-77120  SHIPPED", "  SO-77093  OPEN"]))
        + b"\x11" + addr(20, 1) + e("Command ===>") + b"\x1d\x40" + b"\x13" + b"\x00" * 30
        + b"\x1d\x60")


def _term(tmp_path, data, **kw):
    from cherminal.gui.terminal import TerminalWidget
    from cherminal.session import Session
    s = Session(SessionProfile(transport="telnet", host="h", emulation="ibm3278-2",
                               view="modern", **kw), ProfileStore(tmp_path, site_roots=[]))
    sent = []
    s._reply = sent.append
    s.emulation.reply = sent.append
    s.feed(record(data))
    term = TerminalWidget(s)
    term.resize(900, 640)
    term._fit_font()
    term._on_update()
    return term, sent


def test_themes(app, tmp_path):
    from cherminal.gui import terminal
    term, _ = _term(tmp_path, MENU, modern_theme="paper")
    assert term.colors.bg == (250, 250, 248)
    term, _ = _term(tmp_path, MENU, modern_theme="graphite")
    assert term.colors.bg == (35, 38, 45) and term.colors.min_contrast == 4.5
    term, _ = _term(tmp_path, MENU, modern_theme="session", color_scheme="amber")
    assert term.colors.bg == (20, 10, 0)
    term.set_modern(False)
    assert term.colors.bg == (20, 10, 0)
    term, _ = _term(tmp_path, MENU)                             # auto follows the desktop
    dark = terminal._dark_desktop()
    assert term.colors.bg == ((35, 38, 45) if dark else (250, 250, 248))
    term.set_modern(False)
    assert term.colors.bg == (0, 0, 0)                          # classic scheme again
    term.set_colour_override({"color_scheme": "green"})
    term.set_modern(True)
    assert term.colors.bg == (0, 20, 0)                         # one-off colours win


def test_click_option_types_it_and_double_click_sends(app, tmp_path):
    term, sent = _term(tmp_path, MENU)
    assert [o.code for o in term.choices.options] == ["1", "2"]
    option = term.choices.options[1]
    term.pick(option)
    s = term.session.screen
    assert "".join(c.char for c in s.lines[3][14:17]) == "2  " and sent == []
    term.pick(option, send=True)
    assert sent and sent[-1][:1] == b"\x7d"                     # Enter, with "2" in the field
    assert b"\xf2" in sent[-1]                                   # EBCDIC "2"


def test_list_row_click_and_double_click(app, tmp_path):
    term, sent = _term(tmp_path, LIST)
    rows = term.choices.rows
    assert len(rows) == 2 and term.choices.select == "S"
    term.pick(rows[1])
    s = term.session.screen
    assert (s.y, s.x) == (4, 2) and sent == []
    term.pick(rows[1], send=True)
    assert sent[-1][:1] == b"\x7d" and e("S") in sent[-1]


def test_mouse_double_click_on_a_row(app, tmp_path):
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    from test_hotspots import _mouse
    T = QMouseEvent.Type
    term, sent = _term(tmp_path, LIST)
    _mouse(term, T.MouseMove, 10, 3)
    assert isinstance(term._choice, ListRow)
    assert term.cursor().shape() == Qt.CursorShape.PointingHandCursor
    term.grab()                                                  # paints the hover band
    _mouse(term, T.MouseButtonPress, 10, 3, Qt.MouseButton.LeftButton)
    _mouse(term, T.MouseButtonRelease, 10, 3, Qt.MouseButton.LeftButton)
    assert sent == [] and (term.session.screen.y, term.session.screen.x) == (3, 2)
    pos = QPointF(term.offset_x + 10 * term.cw + 2, term.offset_y + 3 * term.ch + 2)
    term.mouseDoubleClickEvent(QMouseEvent(T.MouseButtonDblClick, pos, pos,
                                           Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                           Qt.KeyboardModifier.NoModifier))
    _mouse(term, T.MouseButtonRelease, 10, 3, Qt.MouseButton.LeftButton)
    assert len(sent) == 1 and sent[0][:1] == b"\x7d"


def test_wheel_pages_only_screens_that_page(app, tmp_path):
    from PyQt6.QtCore import QPoint, QPointF, Qt
    from PyQt6.QtGui import QWheelEvent

    def wheel(term, dy):
        term.wheelEvent(QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, dy),
                                    Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                                    Qt.ScrollPhase.NoScrollPhase, False))
    term, sent = _term(tmp_path, MENU)                         # lists F7=Up F8=Down
    wheel(term, -60)
    assert sent == []                                          # half a notch
    wheel(term, -60)
    assert len(sent) == 1 and sent[0][:1] == b"\xf8"           # PF8
    term.session.emulation.do_action("reset")
    wheel(term, 120)
    assert len(sent) == 1                                      # too soon after the last page
    term._wheel_at -= 1
    wheel(term, 120)
    assert len(sent) == 2 and sent[1][:1] == b"\xf7"           # PF7
    term, sent = _term(tmp_path, LIST)                         # no paging keys
    wheel(term, -120)
    assert sent == []


def test_inline_hint_paints(app, tmp_path):
    term, _ = _term(tmp_path, NUMERIC)
    term.session.send_text("Z")
    assert term.session.emulation.field_error is not None
    term.grab()                                                  # paints the hint label
    term.session.send_text("7")
    assert term.session.emulation.field_error is None


def test_editor_theme(app, tmp_path):
    from cherminal.gui.dialogs import SessionEditor
    ed = SessionEditor(SessionProfile(name="mf", transport="telnet", host="h",
                                      emulation="ibm3278-2", modern_theme="paper"),
                       ProfileStore(tmp_path, site_roots=[]))
    assert ed._build().modern_theme == "paper"
    ed.modern_theme.setCurrentIndex(ed.modern_theme.findData("session"))
    assert ed._build().modern_theme == "session"
    assert "modern_theme" not in SessionProfile().to_dict()
    with pytest.raises(ValueError, match="modern_theme"):
        SessionProfile(modern_theme="neon")
