import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtGui")

from cherminal.config import ProfileStore, SessionProfile  # noqa: E402
from cherminal.gui.colors import (SCHEMES, contrast, ensure_contrast, parse_hex,  # noqa: E402
                                  resolve)

BLACK, WHITE = (0, 0, 0), (255, 255, 255)


def test_wcag_contrast():
    assert contrast(BLACK, WHITE) == pytest.approx(21.0)
    assert contrast((119, 119, 119), WHITE) == pytest.approx(4.48, abs=0.01)


def test_ensure_contrast_keeps_hue_and_meets_ratio():
    dark_blue = (0, 0, 238)
    fixed = ensure_contrast(dark_blue, BLACK, 7)
    assert contrast(fixed, BLACK) >= 7
    assert fixed[2] > fixed[0]                       # still blue
    assert ensure_contrast(WHITE, BLACK, 7) == WHITE  # already fine: untouched
    assert ensure_contrast(dark_blue, BLACK, 1) == dark_blue
    on_white = ensure_contrast((255, 255, 0), WHITE, 7)
    assert contrast(on_white, WHITE) >= 7


def test_high_contrast_schemes_meet_aaa():
    for name, s in SCHEMES.items():
        if s.min_contrast >= 7:
            assert contrast(s.fg, s.bg) >= 7, name
            assert contrast(s.cursor, s.bg) >= 3, name


def test_resolve_layers_session_colours():
    p = SessionProfile(color_scheme="high-contrast", fg_color="#ffff00",
                       palette={"bright-blue": "#80c0ff"}, min_contrast=4.5)
    c = resolve(p)
    assert c.fg == (255, 255, 0) and c.bg == BLACK
    assert c.palette[12] == parse_hex("#80c0ff")
    assert c.min_contrast == 4.5
    assert resolve(SessionProfile(color_scheme="high-contrast")).min_contrast == 7


def test_colour_settings_validate_and_save(tmp_path):
    with pytest.raises(ValueError):
        SessionProfile(fg_color="yellow")
    with pytest.raises(ValueError):
        SessionProfile(palette={"purple": "#800080"})
    with pytest.raises(ValueError):
        SessionProfile(min_contrast=30)
    store = ProfileStore(tmp_path, site_roots=[])
    p = SessionProfile(name="ADA", color_scheme="yellow-on-black", cursor_color="#ff00ff",
                       palette={"blue": "#6fa8ff"}, min_contrast=7)
    store.save(p)
    assert store.load("ADA") == p


def test_terminal_paints_with_minimum_contrast(tmp_path):
    from PyQt6.QtWidgets import QApplication

    from cherminal.gui.terminal import TerminalWidget
    from cherminal.screen import Attr
    from cherminal.session import Session
    app = QApplication.instance() or QApplication([])  # noqa: F841 (keep it alive)
    store = ProfileStore(tmp_path, site_roots=[])
    hc = TerminalWidget(Session(SessionProfile(color_scheme="high-contrast"), store))
    fg, bg = hc._colors(Attr(fg=4), False, False)            # ANSI blue on black
    assert contrast(fg.getRgb()[:3], bg.getRgb()[:3]) >= 7
    fg, bg = hc._colors(Attr(fg=4, invisible=True), False, False)
    assert fg == bg                                          # hidden text stays hidden
    classic = TerminalWidget(Session(SessionProfile(), store))
    fg, _ = classic._colors(Attr(fg=4), False, False)
    assert fg.getRgb()[:3] == (0, 0, 238)                    # untouched without a minimum
