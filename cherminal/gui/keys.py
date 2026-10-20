"""Translate Qt key events into Cherminal key names."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent

K = Qt.Key
_NAMED = {
    K.Key_Up: "Up", K.Key_Down: "Down", K.Key_Left: "Left", K.Key_Right: "Right",
    K.Key_Home: "Home", K.Key_End: "End", K.Key_PageUp: "PageUp", K.Key_PageDown: "PageDown",
    K.Key_Insert: "Insert", K.Key_Delete: "Delete", K.Key_Backspace: "Backspace",
    K.Key_Tab: "Tab", K.Key_Backtab: "Tab", K.Key_Return: "Enter", K.Key_Enter: "KeypadEnter",
    K.Key_Escape: "Escape", K.Key_Space: "Space", K.Key_Pause: "Pause",
    K.Key_Cancel: "Break", K.Key_Print: "Print", K.Key_SysReq: "SysReq",
}
for _i in range(1, 25):
    _NAMED[getattr(K, f"Key_F{_i}")] = f"F{_i}"

_KEYPAD = {
    K.Key_Plus: "KeypadPlus", K.Key_Minus: "KeypadMinus", K.Key_Asterisk: "KeypadMultiply",
    K.Key_Slash: "KeypadDivide", K.Key_Period: "KeypadDecimal", K.Key_Comma: "KeypadComma",
    K.Key_Enter: "KeypadEnter",
}
for _i in range(10):
    _KEYPAD[getattr(K, f"Key_{_i}")] = f"Keypad{_i}"

_MODIFIER_KEYS = {K.Key_Shift, K.Key_Control, K.Key_Alt, K.Key_Meta, K.Key_AltGr,
                  K.Key_CapsLock, K.Key_NumLock, K.Key_ScrollLock, K.Key_Super_L, K.Key_Super_R}

M = Qt.KeyboardModifier


def key_name(event: QKeyEvent) -> tuple[str, str] | None:
    """Return (name, text) for a key event, or None for a bare modifier."""
    key = event.key()
    if key in _MODIFIER_KEYS:
        return None
    mods = event.modifiers()
    text = event.text()
    if mods & M.KeypadModifier and key in _KEYPAD:
        base = _KEYPAD[key]
    elif key in _NAMED:
        base = _NAMED[key]
    elif 0x20 < key < 0x7f:
        base = chr(key).upper()
    else:
        # Non-ASCII keys (e.g. accented letters): no name, just their text.
        return ("", text) if text else None

    parts = []
    if mods & M.ControlModifier:
        parts.append("Ctrl")
    if mods & M.AltModifier:
        parts.append("Alt")
    if mods & M.ShiftModifier or key == K.Key_Backtab:
        parts.append("Shift")
    name = "+".join(parts + [base])

    if mods & M.ControlModifier and not (mods & M.AltModifier):
        if base == "Space":
            text = "\x00"
        elif len(base) == 1 and "@" <= base <= "_":
            text = chr(ord(base) & 0x1F)
    if base == "Space" and not text:
        text = " "
    return name, text
