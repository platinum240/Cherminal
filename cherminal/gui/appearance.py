"""The look of the window around the terminals: menus, tabs, function keys and status bar.

Graphite (dark) and Paper (light) share one layout and differ only in colour;
"system" picks between them from the desktop's light or dark setting, and
"classic" leaves the desktop's own style alone. The terminal screens are not
touched: they keep their own colours whatever the window looks like.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QGuiApplication, QPalette
from PyQt6.QtWidgets import QApplication

APPEARANCES = ("system", "graphite", "paper", "classic")
LABELS = {"system": "Follow the &desktop", "graphite": "&Graphite (dark)",
          "paper": "&Paper (light)", "classic": "&Classic"}
DEFAULT = "system"
RESOURCES = files("cherminal") / "resources"


@dataclass(frozen=True)
class Theme:
    name: str
    dark: bool
    chrome: str         # menu bar, tab strip, toolbars, status bar
    raised: str         # buttons, menus, fields
    tab: str            # the selected tab
    hover: str          # a tab or menu-bar item under the mouse
    line: str           # borders and dividers
    text: str
    muted: str          # unselected tabs, status details, the resting X
    accent: str         # cherry: selected tab line, menu highlight, X on hover
    on_accent: str
    ok: str             # the Connected dot


THEMES = {
    "graphite": Theme("graphite", True, chrome="#16181d", raised="#1f2229", tab="#262a32",
                      hover="#22252c", line="#2c3039", text="#dfe2e8", muted="#8d939e",
                      accent="#e3315a", on_accent="#ffffff", ok="#3ecf8e"),
    "paper": Theme("paper", False, chrome="#f2f0ec", raised="#fbfaf8", tab="#ffffff",
                   hover="#e9e6e1", line="#dcd8d1", text="#22242a", muted="#6c707a",
                   accent="#c8163a", on_accent="#ffffff", ok="#1f9d63"),
}

# What the application looked like before Cherminal styled it, so Classic can
# put it back and "system" can still tell a dark desktop from a light one.
_original: dict = {}


def desktop_is_dark() -> bool:
    """Is the desktop in a dark theme?"""
    hints = QGuiApplication.styleHints()
    scheme = getattr(hints, "colorScheme", None)          # Qt 6.5+
    if scheme is not None and scheme() != Qt.ColorScheme.Unknown:
        return scheme() == Qt.ColorScheme.Dark
    pal = _original.get("palette") or QGuiApplication.palette()
    return pal.window().color().lightness() < 128


def resolve(choice: str, dark: bool) -> Theme | None:
    """The theme an appearance setting means; None for Classic."""
    if choice == "system":
        return THEMES["graphite" if dark else "paper"]
    return THEMES.get(choice)


def palette(t: Theme) -> QPalette:
    """Colours for everything Qt draws itself: dialogs, fields, scroll bars."""
    p = QPalette()
    roles = QPalette.ColorRole
    for role, colour in [(roles.Window, t.chrome), (roles.WindowText, t.text),
                         (roles.Base, t.raised), (roles.AlternateBase, t.tab),
                         (roles.Text, t.text), (roles.Button, t.raised),
                         (roles.ButtonText, t.text), (roles.BrightText, t.on_accent),
                         (roles.Highlight, t.accent), (roles.HighlightedText, t.on_accent),
                         (roles.ToolTipBase, t.raised), (roles.ToolTipText, t.text),
                         (roles.Mid, t.line), (roles.Midlight, t.hover), (roles.Dark, t.line),
                         (roles.Light, t.tab), (roles.Shadow, "#000000"),
                         (roles.PlaceholderText, t.muted), (roles.Link, t.accent)]:
        p.setColor(role, QColor(colour))
    for role in (roles.WindowText, roles.Text, roles.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(t.muted))
    return p


def _icon(name: str) -> str:
    # Forward slashes: a stylesheet url() reads backslashes as escapes on Windows.
    return Path(str(RESOURCES / name)).as_posix()


def stylesheet(t: Theme) -> str:
    close = _icon(f"tab-close-{t.name}.svg")
    close_hover = _icon(f"tab-close-{t.name}-hover.svg")
    check = _icon("check.svg")
    tabs = "QTabWidget#sessionTabs > QTabBar"      # the session tabs; dialogs keep plain tabs
    return f"""
QMainWindow {{ background: {t.chrome}; }}
QMenuBar {{ background: {t.chrome}; color: {t.text}; padding: 3px 6px; border: none; }}
QMenuBar::item {{ padding: 4px 10px; border-radius: 5px; background: transparent; }}
QMenuBar::item:selected {{ background: {t.hover}; }}
QMenu {{ background: {t.raised}; color: {t.text}; border: 1px solid {t.line}; padding: 5px; }}
QMenu::item {{ padding: 6px 28px 6px 14px; border-radius: 5px; }}
QMenu::item:selected {{ background: {t.accent}; color: {t.on_accent}; }}
QMenu::item:disabled {{ color: {t.muted}; }}
QMenu::separator {{ height: 1px; background: {t.line}; margin: 5px 8px; }}
QToolBar#fkeys {{ background: {t.chrome}; border: none; border-bottom: 1px solid {t.line};
    padding: 3px 6px; spacing: 6px; }}
QToolBar#fkeys::handle {{ width: 0; image: none; }}
QToolBar#fkeys QToolButton {{ background: {t.raised}; color: {t.text}; border: 1px solid {t.line};
    border-radius: 6px; padding: 3px 12px; }}
QToolBar#fkeys QToolButton:hover {{ border-color: {t.accent}; }}
QTabWidget#sessionTabs::pane {{ border: none; }}
{tabs} {{ background: {t.chrome}; }}
{tabs}::tab {{ background: transparent; color: {t.muted}; padding: 7px 8px 7px 14px;
    margin: 5px 2px 0 2px; border: none; border-top-left-radius: 7px;
    border-top-right-radius: 7px; min-width: 90px; }}
{tabs}::tab:first {{ margin-left: 6px; }}
{tabs}::tab:hover {{ background: {t.hover}; color: {t.text}; }}
{tabs}::tab:selected {{ background: {t.tab}; color: {t.text}; border-top: 2px solid {t.accent}; }}
{tabs}::close-button {{ image: url("{close}"); subcontrol-position: right; margin-left: 8px;
    width: 16px; height: 16px; border-radius: 4px; }}
{tabs}::close-button:hover {{ image: url("{close_hover}"); }}
QTabWidget#sessionTabs > QToolButton {{ color: {t.muted}; padding: 4px 10px; border-radius: 5px; border: none; }}
QTabWidget#sessionTabs > QToolButton:hover {{ background: {t.hover}; color: {t.text}; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {t.muted};
    border-radius: 3px; background: {t.raised}; }}
QCheckBox::indicator:hover {{ border-color: {t.accent}; }}
QCheckBox::indicator:checked {{ background: {t.accent}; border-color: {t.accent}; image: url("{check}"); }}
QCheckBox::indicator:disabled {{ border-color: {t.line}; }}
QStatusBar {{ background: {t.chrome}; color: {t.muted}; border-top: 1px solid {t.line}; }}
QStatusBar QLabel {{ color: {t.muted}; padding: 3px 6px; }}
QStatusBar::item {{ border: none; }}
"""


def status_html(text: str, t: Theme) -> str:
    """The status line with a dot for the connection state and thin dividers:
    "Connected · TELNET host:23 · VT220 · 80×24"."""
    if not text:
        return ""
    parts = [html.escape(p) for p in text.split(" · ")]
    state = text.split(" · ", 1)[0]
    dot = t.ok if state == "Connected" else t.muted
    sep = f"&nbsp;&nbsp;<span style='color:{t.line}'>│</span>&nbsp;&nbsp;"
    head = (f"<span style='color:{dot}'>●</span>&nbsp; "
            f"<span style='color:{t.text}; font-weight:600'>{parts[0]}</span>")
    return sep.join([head] + parts[1:])


def apply(app: QApplication, choice: str) -> Theme | None:
    """Style the whole application; returns the theme in use (None = Classic)."""
    if not _original:
        _original["palette"] = QPalette(app.palette())
        _original["style"] = app.style().name() if app.style() else ""
    theme = resolve(choice, desktop_is_dark())
    if theme is None:
        app.setStyleSheet("")
        if _original["style"] and app.style().name() != _original["style"]:
            app.setStyle(_original["style"])
        app.setPalette(_original["palette"])
        return None
    # Fusion draws everything from the palette, so dialogs match on every desktop.
    if app.style().name().lower() != "fusion":
        app.setStyle("Fusion")
    app.setPalette(palette(theme))
    app.setStyleSheet(stylesheet(theme))
    return theme
