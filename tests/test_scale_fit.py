"""Scale mode: the text grows to fill the window, and a shell's screen starts
at the top left rather than floating in the middle of the pane."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _term(tmp_path, **kw):
    from cherminal.config import ProfileStore, SessionProfile
    from cherminal.gui.terminal import TerminalWidget
    from cherminal.session import Session
    s = Session(SessionProfile(**kw), ProfileStore(tmp_path, site_roots=[]))
    return TerminalWidget(s)


@pytest.fixture
def mac_font(monkeypatch):
    """The Mac case: a session's "Monospace" is drawn in Menlo, a font with
    other metrics than whatever Qt picks for the name "Monospace". FreeMono
    stands in for Menlo here."""
    from cherminal import system
    real = system.font_family
    monkeypatch.setattr(system, "font_family",
                        lambda family: "FreeMono" if family == "Monospace" else real(family))


def _fits(term):
    s = term.session.screen
    area = term._grid_area()
    assert term.cw * s.cols <= area.width() and term.ch * s.rows <= area.height()
    # One more half point would no longer fit: the text is as big as it can be.
    return (area.width() - term.cw * s.cols < term.cw * s.cols * 0.08
            or area.height() - term.ch * s.rows < term.ch * s.rows * 0.08)


def test_scale_fills_the_window_with_the_font_actually_drawn(app, tmp_path, mac_font):
    term = _term(tmp_path, transport="local", emulation="xterm")
    term.resize(1400, 480)               # the height sets the size
    term._fit_font()
    assert term.term_font.family() == "FreeMono"
    assert _fits(term)


def test_shell_screen_starts_at_the_top_left(app, tmp_path, mac_font):
    term = _term(tmp_path, transport="local", emulation="xterm")
    term.resize(925, 665)
    term._fit_font()
    area = term._grid_area()
    assert (term.offset_x, term.offset_y) == (area.x(), area.y())


def test_block_mode_screen_stays_centred(app, tmp_path):
    term = _term(tmp_path, transport="telnet", host="h", emulation="ibm3278-2")
    term.resize(1400, 480)               # far wider than the 80x24 grid needs
    term._fit_font()
    area = term._grid_area()
    s = term.session.screen
    assert term.offset_x == area.x() + (area.width() - term.cw * s.cols) // 2
    assert term.offset_x > area.x()
