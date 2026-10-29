"""Custom layouts (Modern view, phase 4): rule files, matching, reading a
screen through a rule, making a rule from a screen, and the form."""

import os
import tomllib

import pytest
from test_ibm3270 import addr, e, record

from cherminal.config import ProfileStore, SessionProfile
from cherminal.emulation.base import InputField
from cherminal.layouts import LayoutError, find, make, parse, view

RULE = '''
[screen]
name = "Customer inquiry"
match = [{ row = 1, col = 3, text = "CUST01" }]
title = { row = 5, col = 22, len = 30 }

[[field]]
label = "Customer no."
at = { row = 4, col = 23, len = 10 }
place = "header"

[[value]]
label = "Status"
at = { row = 8, col = 22, len = 8 }
card = "Account"
badges = { ACTIVE = "good", HOLD = "warn" }

[[value]]
label = "Credit used"
at = { row = 9, col = 22, len = 12 }
card = "Credit"
kind = "money"

[[table]]
title = "Recent orders"
rows = "12-14"
select = { col = 3, action = "S" }
columns = ["Order", "Date", "Amount:money", "Status:badge"]
badges = { SHIPPED = "good", OPEN = "warn" }
'''

# The screen the rule is for, as a 3270 host sends it.
SCREEN = (b"\xf5\xc3"
          + b"\x11" + addr(0, 1) + b"\x1d\x60" + e("CUST01")
          + b"\x11" + addr(0, 26) + b"\x1d\xe8" + e("CUSTOMER INQUIRY") + b"\x1d\x60"
          + b"\x11" + addr(3, 1) + b"\x1d\x60" + e("Customer number . .") + b"\x1d\x50"
          + e("0048213") + b"\x00" * 3 + b"\x1d\x60"
          + b"\x11" + addr(4, 1) + e("Name  . . . . . . .") + b"\x1d\xe8"
          + e("HARGREAVES SUPPLY CO") + b"\x1d\x60"
          + b"\x11" + addr(7, 1) + e("Account status  . .") + b"\x1d\xe8" + e("ACTIVE")
          + b"\x1d\x60"
          + b"\x11" + addr(8, 1) + e("Credit used . . . .") + b"\x1d\xe8" + e("18,442.17")
          + b"\x1d\x60"
          + b"\x11" + addr(10, 1) + b"\x1d\xe8"
          + e("Sel  Order      Date          Amount  Status") + b"\x1d\x60"
          + b"".join(b"\x11" + addr(11 + i, 1) + b"\x1d\x40\x00\x1d\x60" + e(t)
                     for i, t in enumerate(["  SO-77120   10/24/26    3,118.40  SHIPPED",
                                            "  SO-77093   10/18/26    9,870.00  OPEN"]))
          + b"\x11" + addr(16, 1) + e("Type S beside an order and press Enter to view it.")
          + b"\x11" + addr(20, 1) + e("Command ===>") + b"\x1d\x40" + b"\x13" + b"\x00" * 50
          + b"\x1d\x60"
          + b"\x11" + addr(22, 1) + e("F1=Help  F3=Exit  F12=Cancel"))


def _screen():
    from cherminal.emulation import create
    from cherminal.screen import Screen
    screen = Screen(80, 24)
    em = create("ibm3278-2", screen, lambda data: None)
    em.feed(record(SCREEN))
    lines = ["".join(" " if c.attr.invisible else c.char for c in line) for line in screen.lines]
    return lines, em.input_fields()


# ------------------------------------------------------------------- rules


def test_rule_reads_the_screen():
    layout = parse(tomllib.loads(RULE), "layouts/customer-inquiry.toml")
    lines, fields = _screen()
    assert layout.matches(lines) and layout.source == "customer-inquiry.toml"
    assert find([layout], lines) is layout
    assert not layout.matches(["x" * 80] * 24)
    form = view(layout, lines, fields)
    assert form.title == "HARGREAVES SUPPLY CO"
    [number] = form.header
    assert (number.text, number.field) == ("0048213", InputField(3, 22, 10, numeric=True))
    cards = dict(form.cards)
    assert [(v.text, v.tone) for v in cards["Account"]] == [("ACTIVE", "good")]
    assert [(v.text, v.kind) for v in cards["Credit"]] == [("18,442.17", "money")]
    [orders] = form.tables
    assert orders.select == (3, "S")
    assert [r for r, _ in orders.rows] == [11, 12]          # the blank third row is left out
    assert [(c.text, c.tone) for c in orders.rows[1][1]] == [
        ("SO-77093", ""), ("10/18/26", ""), ("9,870.00", ""), ("OPEN", "warn")]


def test_rule_options():
    rule = tomllib.loads(RULE)
    rule["screen"]["match"] = [{"row": 1, "text": "INQUIRY"}]       # anywhere on row 1
    rule["screen"]["session"] = "CICS production"
    rule["table"][0]["columns"] = [{"name": "Order", "col": 7, "len": 10},
                                   {"name": "Status", "col": 40, "len": 10, "kind": "badge"}]
    layout = parse(rule)
    lines, fields = _screen()
    assert not layout.matches(lines, "Other session")
    assert layout.matches(lines, "CICS production")
    [orders] = view(layout, lines, fields).tables
    assert [c.text for c in orders.rows[0][1]] == ["SO-77120", "SHIPPED"]


@pytest.mark.parametrize("change, message", [
    (lambda r: r["screen"].pop("match"), "match"),
    (lambda r: r["screen"].pop("name"), "name"),
    (lambda r: r["value"][0]["badges"].update(X="pink"), "badge colours"),
    (lambda r: r["table"][0].update(rows="15-12"), "rows"),
    (lambda r: r["field"][0].update(at={"row": 0, "col": 1, "len": 2}), "row"),
    (lambda r: r["value"][0].update(kind="date"), "kind"),
    (lambda r: r.update(extra={}), "unknown"),
])
def test_bad_rules_say_what_is_wrong(change, message):
    rule = tomllib.loads(RULE)
    change(rule)
    with pytest.raises(LayoutError, match=message):
        parse(rule, "bad.toml")


def test_make_a_rule_from_a_screen():
    lines, fields = _screen()
    text = make(lines, fields)
    layout = parse(tomllib.loads(text))
    assert layout.name == "Customer inquiry" and layout.matches(lines)
    assert layout.match[0].text == "CUST01"
    labels = [i.label for i in layout.items]
    assert labels[:2] == ["Customer number", "Command"]
    assert "Credit used" in labels and "Account status" in labels
    money = next(i for i in layout.items if i.label == "Credit used")
    assert money.kind == "money"
    [table] = layout.tables
    assert (table.first, table.last, table.select) == (12, 13, (3, "S"))
    assert [c.name for c in table.columns] == ["Order", "Date", "Amount", "Status"]
    assert table.columns[2].kind == "money"
    form = view(layout, lines, fields)
    assert form.tables[0].rows[0][1][0].text == "SO-77120"


def test_store_layers_shared_and_own_layouts(tmp_path):
    site, user = tmp_path / "site", tmp_path / "user"
    (site / "layouts").mkdir(parents=True)
    (site / "layouts" / "customer-inquiry.toml").write_text(RULE)
    (site / "layouts" / "orders.toml").write_text(RULE.replace("Customer inquiry", "Orders"))
    (site / "layouts" / "broken.toml").write_text("[screen]\nname = 'x'\n")
    store = ProfileStore(user, site_roots=[site])
    layouts, errors = store.layouts()
    assert [lay.name for lay in layouts] == ["Customer inquiry", "Orders"]
    assert len(errors) == 1 and "broken.toml" in errors[0]
    store.save_layout("Orders", RULE.replace("Customer inquiry", "My orders"))
    assert [lay.name for lay in store.layouts()[0]] == ["Customer inquiry", "My orders"]
    with pytest.raises(LayoutError):
        store.save_layout("nope", "[screen]\nname = 'x'\n")
    assert not (user / "layouts" / "nope.toml").exists()


# ------------------------------------------------------------------ GUI

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _term(tmp_path, view="modern"):
    from cherminal.gui.terminal import TerminalWidget
    from cherminal.session import Session
    (tmp_path / "layouts").mkdir(exist_ok=True)
    (tmp_path / "layouts" / "customer-inquiry.toml").write_text(RULE)
    store = ProfileStore(tmp_path, site_roots=[])
    s = Session(SessionProfile(name="CICS production", transport="telnet", host="h",
                               emulation="ibm3278-2", view=view), store)
    sent = []
    s._reply = sent.append
    s.emulation.reply = sent.append
    s.feed(record(SCREEN))
    term = TerminalWidget(s)
    term.resize(1000, 700)
    term._apply_resize()
    term._on_update()
    return term, sent


def _key(widget, key, text=""):
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtWidgets import QApplication
    QApplication.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, key,
                                             Qt.KeyboardModifier.NoModifier, text))


def test_form_types_into_the_screen_fields(app, tmp_path):
    from PyQt6.QtCore import Qt

    from cherminal.gui.layoutview import FieldBox
    term, sent = _term(tmp_path)
    assert term.matched.name == "Customer inquiry" and not term.layout_view.isHidden()
    assert term.trail.titles == ["Customer inquiry"]
    [box] = term.layout_view.findChildren(FieldBox)
    assert box.text() == "0048213"
    box.setText("0049102")
    box.textEdited.emit("0049102")
    s = term.session.screen
    assert "".join(c.char for c in s.lines[3][22:29]) == "0049102" and sent == []
    _key(box, Qt.Key.Key_F3)                                # function keys go to the host
    assert sent[-1][:1] == b"\xf3"
    term.session.feed(record(SCREEN))                       # the host answers
    term._on_update()
    _key(box, Qt.Key.Key_Return)
    assert sent[-1][:1] == b"\x7d"


def test_form_table_rows_select(app, tmp_path):
    term, sent = _term(tmp_path)
    [table] = term.layout_view._tables
    table.cellClicked.emit(1, 0)                            # click: the cursor goes there
    s = term.session.screen
    assert (s.y, s.x) == (12, 2) and sent == []
    table.cellDoubleClicked.emit(1, 0)                      # double-click: S and Enter
    assert sent[-1][:1] == b"\x7d" and e("S") in sent[-1]


def test_show_screen_and_history_hide_the_form(app, tmp_path):
    term, _ = _term(tmp_path)
    term.toggle_layout()
    assert term.layout_view.isHidden() and term.show_screen
    term.toggle_layout()
    assert not term.layout_view.isHidden()
    term.press_key("enter")
    term.session.feed(record(SCREEN))
    term._on_update()
    term.view_history(-1)
    assert term.layout_view.isHidden()
    term.view_live()
    assert not term.layout_view.isHidden()
    term.set_modern(False)
    assert term.layout_view.isHidden()
    term.grab()


def test_classic_view_never_uses_layouts(app, tmp_path):
    term, _ = _term(tmp_path, view="classic")
    assert term.matched is None and term.layout_view.isHidden()


def test_make_layout_dialog_saves_and_every_tab_reloads(app, tmp_path):
    from cherminal.gui.app import MainWindow
    from cherminal.gui.layoutview import MakeLayoutDialog
    term, _ = _term(tmp_path)
    (tmp_path / "layouts" / "customer-inquiry.toml").unlink()
    term.reload_layouts()
    assert term.matched is None
    win = MainWindow(term.session.store)
    term.connect_session = lambda: None
    term.layouts_saved.connect(win.reload_layouts)
    win.tabs.addTab(term, "mf")
    win._tab_changed(0)
    assert win.make_layout_action.isVisible()
    lines, fields = _screen()
    dlg = MakeLayoutDialog(term, make(lines, fields))
    dlg.text.setPlainText("[screen]\nname = 'x'\n")
    dlg.save()
    assert dlg.saved is None and not dlg.error.isHidden()   # says what's wrong, stays open
    dlg.text.setPlainText(make(lines, fields))
    dlg.save()
    assert dlg.saved == tmp_path / "layouts" / "customer-inquiry.toml"
    term.layouts_saved.emit()
    assert term.matched is not None and term.matched.name == "Customer inquiry"
