"""Modern view, phase 3: screen titles and the breadcrumb, screen history,
tables as CSV, and the command palette."""

import os

import pytest
from test_ibm3270 import addr, e, record
from test_ibm5250 import PASSWORD, USER
from test_ibm5250 import signed_on as signed_on_5250

from cherminal import policy
from cherminal.config import ProfileStore, SessionProfile
from cherminal.emulation.base import InputField
from cherminal.emulation.navigation import (
    ScreenHistory,
    Snapshot,
    Trail,
    find_tables,
    screen_text,
    screen_title,
    table_csv,
)
from cherminal.screen import Screen

# ------------------------------------------------------------------- titles

ACTIVE_JOBS = """\
                          Work with Active Jobs                      SYS0001
                                                            10/29/26  15:09:41
 CPU %:     .0     Elapsed time:   00:00:00     Active jobs:   212

 Type options, press Enter.
   2=Change   3=Hold   4=End   5=Work with   6=Release   7=Display message

 Opt  Subsystem/Job  User        Type  CPU %  Function        Status
      QBATCH         QSYS        SBS     .0                   DEQW
        QZDASOINIT   QUSER       BCI     .0   PGM-QZDASOINIT  TIMW
      QINTER         QSYS        SBS     1.2                  DEQW
                                                                         More...
 Parameters or command
 ===>
 F3=Exit   F5=Refresh   F7=Find   F10=Restart statistics""".split("\n")


def test_screen_titles():
    assert screen_title(ACTIVE_JOBS) == "Work with Active Jobs"
    ispf = ["  Menu  Utilities  Compilers  Options  Status  Help",
            " " + "-" * 78, "                 ISPF Primary Option Menu", "Option ===> "]
    assert screen_title(ispf) == "ISPF Primary Option Menu"
    cics = ["CUST01               CUSTOMER INQUIRY              10/29/26  3:09 PM"]
    assert screen_title(cics) == "Customer inquiry"          # shouting tidied, ids skipped
    typed = ["  Search for   ACCOUNT HISTORY REPORT    ".ljust(80)]
    field = InputField(0, 15, 30)
    assert screen_title(typed, [field]) == "Search for"     # what the user typed isn't a title
    assert screen_title([""] * 24) == ""


def test_trail_goes_back_to_earlier_screens():
    trail = Trail(limit=3)
    for title in ["Main menu", "Customer list", "", "Customer inquiry", "Customer inquiry"]:
        trail.visit(title)
    assert trail.titles == ["Main menu", "Customer list", "Customer inquiry"]
    trail.visit("Customer list")                            # PF3 back
    assert trail.titles == ["Main menu", "Customer list"]
    for title in ["A", "B", "C"]:
        trail.visit(title)
    assert trail.titles == ["A", "B", "C"]


# ------------------------------------------------------------------- tables


def test_tables_and_csv():
    tables = find_tables(ACTIVE_JOBS)
    assert len(tables) == 1                                 # the loose header lines aren't one
    t = tables[0]
    assert t.header == ["Opt", "Subsystem/Job", "User", "Type", "CPU %", "Function", "Status"]
    assert t.rows[1] == ["", "QZDASOINIT", "QUSER", "BCI", ".0", "PGM-QZDASOINIT", "TIMW"]
    ruled = ["  Name                Balance    Status",
             "  ------------------  ---------  ------",
             "  HARGREAVES          -12.50     A",
             "  SMITH               =HYPERLINK B", ""]
    t = find_tables(ruled)[0]
    assert table_csv(t).splitlines() == ["Name,Balance,Status", "HARGREAVES,-12.50,A",
                                         "SMITH,'=HYPERLINK,B"]   # never a live formula
    assert find_tables(["Just some text", "on a few", "lines"]) == []


# ------------------------------------------------------------------ history


def test_history_blanks_hidden_fields_and_skips_repeats():
    em, screen, _ = signed_on_5250()
    em.click(USER)
    em.type_text("QSECOFR")
    em.click(PASSWORD)
    em.type_text("SECRET")
    snap = Snapshot.of(screen, em.input_fields(), 100.0)
    assert "QSECOFR" in snap.text[5] and "SECRET" not in "".join(snap.text)
    assert snap.title == "Sign On"
    history = ScreenHistory(limit=2)
    history.add(snap)
    history.add(Snapshot.of(screen, em.input_fields(), 101.0))     # the same screen again
    history.add(Snapshot.of(Screen(80, 24), [], 102.0))           # a blank one
    assert len(history) == 1
    for n in range(3):
        s = Screen(80, 24)
        s.lines[0][0].char = str(n)
        history.add(Snapshot.of(s, [], 103.0 + n))
    assert [h.text[0][0] for h in history.items] == ["1", "2"]
    assert screen_text(["abc  ", "", "d", "", ""]) == "abc\n\nd"


PANEL = (b"\xf5\xc3"
         + b"\x11" + addr(0, 20) + b"\x1d\x60" + e("CUSTOMER INQUIRY")
         + b"\x11" + addr(3, 1) + e("Customer number . .")
         + b"\x1d\x40" + b"\x13" + b"\x00" * 8 + b"\x1d\x60"
         + b"\x11" + addr(5, 1) + e("Password") + b"\x1d\x4c" + b"\x00" * 8 + b"\x1d\x60"
         + b"\x11" + addr(22, 1) + e("F3=Exit  F12=Cancel"))


def _session(tmp_path, **kw):
    from cherminal.session import Session
    s = Session(SessionProfile(transport="telnet", host="h", emulation="ibm3278-2", **kw),
                ProfileStore(tmp_path, site_roots=[]))
    sent = []
    s._reply = sent.append
    s.emulation.reply = sent.append
    s.feed(record(PANEL))
    return s, sent


def test_session_keeps_screens_only_when_asked(tmp_path):
    s, sent = _session(tmp_path)
    s.send_text("42")
    s.run_binding(s.keymap.lookup("Enter"))
    assert sent and len(s.history) == 0                     # classic: nothing kept
    s, sent = _session(tmp_path)
    s.keep_history = True
    s.send_text("42")
    s.run_binding(s.keymap.lookup("Pause"))                 # Clear blanks the screen...
    assert len(s.history) == 1                              # ...after it was kept
    kept = s.history.items[0]
    assert kept.title == "Customer inquiry" and "42" in kept.text[3]
    policy.set_current(policy.Policy.from_dict({"screen_history": False}))
    try:
        s, _ = _session(tmp_path)
        s.keep_history = True
        s.run_binding(s.keymap.lookup("Enter"))
        assert len(s.history) == 0
    finally:
        policy.set_current(policy.Policy())
    with pytest.raises(policy.PolicyError, match="screen_history"):
        policy.Policy.from_dict({"screen_history": "no"})


# ------------------------------------------------------------------ palette


def test_palette_ranking():
    pytest.importorskip("PyQt6.QtWidgets")
    from cherminal.gui.palette import Item, matches, rank
    items = [Item("Actions", "Print screen", "", None),
             Item("Transactions", "CUST01", "Customer inquiry", None),
             Item("Transactions", "ORD02", "Order inquiry", None),
             Item("Macros", "login", "macro", None)]
    assert [i.label for i in matches("inq", items)] == ["CUST01", "ORD02"]
    assert [i.label for i in matches("order inq", items)] == ["ORD02"]
    assert [i.section for i in matches("", items)] == ["Transactions", "Transactions",
                                                       "Macros", "Actions"]
    assert rank("print", items[0]) < rank("screen", items[0])
    assert rank("xyz", items[0]) is None


# ------------------------------------------------------------------ GUI

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _term(tmp_path, **kw):
    from cherminal.gui.terminal import TerminalWidget
    s, sent = _session(tmp_path, **kw)
    term = TerminalWidget(s)
    term.resize(900, 640)
    term._apply_resize()
    term._on_update()
    return term, sent


def _key(widget, key, text=""):
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtWidgets import QApplication
    QApplication.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, key,
                                             Qt.KeyboardModifier.NoModifier, text))


def test_breadcrumb_bar_sits_above_the_screen(app, tmp_path):
    term, _ = _term(tmp_path)
    assert term.nav.isHidden()
    term.set_modern(True)
    assert not term.nav.isHidden() and term.trail.titles == ["Customer inquiry"]
    assert term.offset_y >= term.nav.height()               # the grid starts below the bar
    assert term.ch * term.session.screen.rows + term.offset_y <= term.height()
    term.session.feed(record(b"\xf5\xc3" + b"\x11" + addr(0, 25) + e("ORDER LIST")))
    term._on_update()
    assert term.trail.titles == ["Customer inquiry", "Order list"]
    term.grab()
    term.set_modern(False)
    assert term.nav.isHidden()


def test_history_view_is_read_only(app, tmp_path):
    from PyQt6.QtCore import Qt
    term, sent = _term(tmp_path, view="modern")
    term.session.send_text("42")
    term.press_key("enter")
    term.session.feed(record(b"\xf5\xc3" + b"\x11" + addr(0, 25) + e("ORDER LIST")))
    term._on_update()
    assert len(term.session.history) == 1
    assert term.history_index("Customer inquiry") == 0
    term.view_history(-1)
    assert term.viewing == 0 and "42" in term.screen_lines()[3]
    term.grab()                                             # paints the past screen
    count = len(sent)
    _key(term, Qt.Key.Key_A, "a")                           # any key: back to live, not sent
    assert term.viewing is None and len(sent) == count
    assert "a" not in term.screen_lines()[0]
    term.view_history(0)
    _key(term, Qt.Key.Key_Escape)
    assert term.viewing is None
    term.view_history(5)                                    # past the end: the live screen
    assert term.viewing is None


def test_copy_and_export_never_include_hidden_fields(app, tmp_path):
    from PyQt6.QtGui import QGuiApplication
    term, _ = _term(tmp_path, view="modern")
    emu = term.session.emulation
    emu.click(5 * 80 + 10)
    emu.type_text("HUNTER2")
    term.copy_screen()
    text = QGuiApplication.clipboard().text()
    assert "CUSTOMER INQUIRY" in text and "HUNTER2" not in text
    term.limited = True
    term.session.feed(record(b"\xf5\xc3" + b"".join(
        b"\x11" + addr(4 + i, 2) + e(row) for i, row in enumerate(
            ["Order     Status", "SO-77120  SHIPPED", "SO-77093  OPEN"]))))
    term.export_table()
    assert QGuiApplication.clipboard().text().splitlines() == [
        "Order,Status", "SO-77120,SHIPPED", "SO-77093,OPEN"]


def test_palette_runs_transactions_and_keys(app, tmp_path):
    from PyQt6.QtCore import Qt
    term, sent = _term(tmp_path, view="modern", transactions={"CUST01": "Customer inquiry"},
                       macros={"hello": "HELLO"})
    term.session.key("Ctrl+K")                              # action:palette
    pal = term.command_palette
    assert pal is not None and not pal.isHidden()
    labels = [i.label for i in pal.items]
    assert {"CUST01", "hello", "Exit", "Copy screen text"} <= set(labels)
    pal.field.setText("exit")
    assert pal.chosen().label == "Exit"
    pal.field.setText("cust")
    _key(pal.field, Qt.Key.Key_Return)                      # runs CUST01: Clear first
    assert term.command_palette is None and sent[-1][:1] == b"\x6d"   # AID Clear
    term._transaction_tick()                                # host hasn't answered: waits
    assert term._pending is not None
    term.session.feed(record(b"\xf5\xc3"))                  # the host unlocks the keyboard
    term._transaction_tick()
    assert term._pending is None and sent[-1][:1] == b"\x7d" and e("CUST01") in sent[-1]


def test_5250_transaction_needs_a_command_line(app, tmp_path):
    from test_ibm5250 import SIGNON
    from test_ibm5250 import record as record5250

    from cherminal.gui.terminal import TerminalWidget
    from cherminal.session import Session
    s = Session(SessionProfile(transport="telnet", host="h", emulation="ibm3179-2",
                               view="modern"), ProfileStore(tmp_path, site_roots=[]))
    sent = []
    s._reply = sent.append
    s.emulation.reply = sent.append
    s.feed(record5250(SIGNON))
    term = TerminalWidget(s)
    notes = []
    term.message.connect(notes.append)
    term.run_transaction("WRKACTJOB")
    assert sent == [] and notes == ["There is no command line on this screen"]


def test_window_palette_actions_and_editor(app, tmp_path):
    from cherminal.gui.app import MainWindow
    from cherminal.gui.dialogs import SessionEditor
    win = MainWindow(ProfileStore(tmp_path, site_roots=[]))
    term, _ = _term(tmp_path, view="modern")
    term.connect_session = lambda: None
    term.palette_extra = win._palette_items
    win.tabs.addTab(term, "mf")
    win._tab_changed(0)
    assert win.palette_action.isVisible() and win.history_action.isVisible()
    labels = [i.label for i in win._palette_items(term)]
    assert "Reconnect" in labels and "Classic view" in labels
    win.open_palette()
    assert term.command_palette is not None and "Reconnect" in [i.label for i in term.command_palette.items]
    ed = SessionEditor(SessionProfile(name="mf", transport="telnet", host="h",
                                      emulation="ibm3278-2",
                                      transactions={"CUST01": "Customer inquiry"}),
                       ProfileStore(tmp_path, site_roots=[]))
    assert ed._build().transactions == {"CUST01": "Customer inquiry"}


# ------------------------------------------------------- 0.11.1 fixes


def _click(widget, pos):
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtWidgets import QApplication
    pos = QPointF(pos)
    glob = QPointF(widget.mapToGlobal(pos.toPoint()))
    for kind in (QMouseEvent.Type.MouseButtonPress, QMouseEvent.Type.MouseButtonRelease):
        QApplication.sendEvent(widget, QMouseEvent(
            kind, pos, glob, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton
            if kind == QMouseEvent.Type.MouseButtonPress else Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier))


def test_palette_closes_on_a_click_outside_without_passing_it_on(app, tmp_path):
    from PyQt6.QtCore import QPoint, Qt
    term, sent = _term(tmp_path, view="modern")
    term.show()
    s = term.session.screen
    start = (s.y, s.x)
    term.open_palette()
    pal = term.command_palette
    # A click on the command line, behind nothing: the palette closes and
    # the cursor stays where it was.
    target = QPoint(int(term.offset_x + 30 * term.cw), int(term.offset_y + 20.5 * term.ch))
    _click(term, target)
    assert term.command_palette is None and pal.isHidden() and (s.y, s.x) == start
    _click(term, target)                                    # the next click acts normally
    term.open_palette()
    _key(term, Qt.Key.Key_Escape)                           # Esc with the focus anywhere
    assert term.command_palette is None
    term.open_palette()
    from PyQt6.QtWidgets import QToolButton
    [close] = [b for b in term.command_palette.findChildren(QToolButton) if b.text() == "✕"]
    close.click()
    assert term.command_palette is None and sent == []


def test_modern_button_names_the_other_view(app, tmp_path):
    from cherminal.gui.app import MainWindow
    win = MainWindow(ProfileStore(tmp_path, site_roots=[]))
    term, _ = _term(tmp_path)
    term.connect_session = lambda: None
    win.tabs.addTab(term, "mf")
    win._tab_changed(0)
    assert win.modern_button.text() == "Modern view"
    win.modern_button.click()
    assert term.modern and win.modern_button.text() == "Classic view"
    win.modern_button.click()
    assert not term.modern and win.modern_button.text() == "Modern view"


def test_modern_screen_sits_on_a_rounded_card(app, tmp_path):
    term, _ = _term(tmp_path, view="modern")
    card = term._card()
    s = term.session.screen
    assert card.top() >= term.nav.height() and card.left() > 0
    assert term.offset_x >= card.left() + 8 and term.offset_y >= card.top() + 8
    assert term.offset_x + term.cw * s.cols <= card.right() - 7
    assert term.offset_y + term.ch * s.rows <= card.bottom() - 7
    term.grab()
