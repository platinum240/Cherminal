"""Translate Qt key events into Cherminal key names.

On macOS Qt reports the Command key as Control and the Control key as Meta,
so that Ctrl+C in a shortcut means Cmd+C there. For the host it is the
other way round: the Control key sends control codes and Command never
reaches the host (it drives the menus). Option types accented characters
on a Mac; a session's ``option_key`` setting decides whether Option is Alt
instead (``alt``), only the left one is (``left-alt``, the right one still
types characters), or neither is (``text``).
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent

from ..system import IS_MAC

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

_NX_DEVICE_LEFT_ALT = 0x20      # NSEvent modifier flag: the left Option key

M = Qt.KeyboardModifier


def option_is_alt(event: QKeyEvent, option_key: str) -> bool:
    """macOS: is the Option key held for this event acting as Alt?"""
    if not event.modifiers() & M.AltModifier or option_key == "text":
        return False
    if option_key == "left-alt":
        return bool(event.nativeModifiers() & _NX_DEVICE_LEFT_ALT)
    return True


def key_name(event: QKeyEvent, option_key: str = "left-alt",
             mac: bool = IS_MAC) -> tuple[str, str] | None:
    """Return (name, text) for a key event, or None for a bare modifier.

    ``option_key`` only matters on macOS (see the module notes).
    """
    key = event.key()
    if key in _MODIFIER_KEYS:
        return None
    mods = event.modifiers()
    text = event.text()
    if mac:
        if mods & M.ControlModifier:
            return None             # Command: the menus' key, never the host's
        ctrl = bool(mods & M.MetaModifier)
        alt = option_is_alt(event, option_key)
        if alt and 0x20 < key < 0x7f:
            # Option would have typed an accented letter; Alt wants the key itself.
            text = chr(key).lower() if not mods & M.ShiftModifier else chr(key)
        elif mods & M.AltModifier and not alt and not ctrl and text and key not in _NAMED:
            return ("", text)       # Option typing a character
        if key == K.Key_Help:
            key = K.Key_Insert      # Mac extended keyboards have Help where Insert is
    else:
        ctrl = bool(mods & M.ControlModifier)
        alt = bool(mods & M.AltModifier)
    if mac and key == K.Key_Clear:
        base = "Clear"              # the Mac keypad's key where Num Lock is
    elif mods & M.KeypadModifier and key in _KEYPAD:
        base = _KEYPAD[key]
    elif key in _NAMED:
        base = _NAMED[key]
    elif 0x20 < key < 0x7f:
        base = chr(key).upper()
    else:
        # Non-ASCII keys (e.g. accented letters): no name, just their text.
        return ("", text) if text else None

    parts = []
    if ctrl:
        parts.append("Ctrl")
    if alt:
        parts.append("Alt")
    if mods & M.ShiftModifier or key == K.Key_Backtab:
        parts.append("Shift")
    name = "+".join(parts + [base])

    if ctrl and not alt:
        if base == "Space":
            text = "\x00"
        elif len(base) == 1 and "@" <= base <= "_":
            text = chr(ord(base) & 0x1F)
    if base == "Space" and not text:
        text = " "
    return name, text
