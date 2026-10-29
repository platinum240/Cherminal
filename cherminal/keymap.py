"""Keyboard mapping.

Keys are named ``[Ctrl+][Alt+][Shift+]<Key>`` (see docs/SPEC.md). A
binding is a byte string in Cherminal escape notation, or ``action:<name>``.
Bindings prefixed ``app:`` apply in application cursor mode and ``kp:`` in
application keypad mode.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .system import IS_MAC, IS_WINDOWS

MODIFIERS = ("Ctrl", "Alt", "Shift")

NAMED_KEYS = (
    [f"F{i}" for i in range(1, 25)]
    + ["Up", "Down", "Left", "Right", "Home", "End", "PageUp", "PageDown",
       "Insert", "Delete", "Backspace", "Tab", "Enter", "Escape", "Space", "Break", "Pause",
       "Print", "SysReq", "Clear"]
    + [f"Keypad{i}" for i in range(10)]
    + ["KeypadEnter", "KeypadPlus", "KeypadMinus", "KeypadMultiply",
       "KeypadDivide", "KeypadDecimal", "KeypadComma"]
)
_CANONICAL = {k.lower(): k for k in NAMED_KEYS}


def normalize_key(name: str) -> str:
    """Canonical spelling of a key name, e.g. ``shift+ctrl+f1`` -> ``Ctrl+Shift+F1``.

    A mode prefix (``app:`` / ``kp:``) is preserved.
    """
    prefix = ""
    if ":" in name and name.split(":", 1)[0].lower() in ("app", "kp"):
        prefix, name = name.split(":", 1)
        prefix = prefix.lower() + ":"
    parts = name.split("+")
    # "Ctrl++" names the plus key itself.
    if name.endswith("++"):
        parts = parts[:-2] + ["+"]
    base = parts[-1]
    mods = {p.strip().lower() for p in parts[:-1]}
    aliases = {"control": "ctrl", "meta": "alt", "option": "alt"}
    mods = {aliases.get(m, m) for m in mods}
    unknown = mods - {m.lower() for m in MODIFIERS}
    if unknown:
        raise ValueError(f"unknown modifier in key {name!r}: {', '.join(sorted(unknown))}")
    base = _CANONICAL.get(base.lower(), base if len(base) == 1 else None)
    if base is None:
        raise ValueError(f"unknown key name {name!r}")
    if len(base) == 1 and base.isalpha():
        base = base.upper()
    ordered = [m for m in MODIFIERS if m.lower() in mods]
    return prefix + "+".join(ordered + [base])


# ------------------------------------------------------------ escape notation

def parse_notation(text: str) -> str:
    r"""Decode ``\e``, ``\r``, ``\xHH``, ``^A`` style notation into characters."""
    out = []
    i = 0
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text):
            n = text[i + 1]
            simple = {"e": "\x1b", "E": "\x1b", "r": "\r", "n": "\n", "t": "\t",
                      "b": "\b", "0": "\x00", "\\": "\\", "^": "^"}
            if n in simple:
                out.append(simple[n])
                i += 2
                continue
            if n == "x" and _is_hex(text[i + 2:i + 4]):
                out.append(chr(int(text[i + 2:i + 4], 16)))
                i += 4
                continue
            raise ValueError(f"bad escape \\{n} in {text!r}")
        if c == "^" and i + 1 < len(text):
            n = text[i + 1]
            if n == "?":
                out.append("\x7f")
            elif "@" <= n.upper() <= "_":
                out.append(chr(ord(n.upper()) - 0x40))
            else:
                raise ValueError(f"bad caret escape ^{n} in {text!r}")
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _is_hex(s: str) -> bool:
    return len(s) == 2 and all(ch in "0123456789abcdefABCDEF" for ch in s)


def format_notation(data: str) -> str:
    """Inverse of :func:`parse_notation`, used by the keymap editor."""
    out = []
    for ch in data:
        o = ord(ch)
        if ch == "\x1b":
            out.append("\\e")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "^":
            out.append("\\^")
        elif o == 0x7f:
            out.append("^?")
        elif o < 0x20:
            out.append("^" + chr(o + 0x40))
        elif 0x80 <= o <= 0x9f:
            out.append(f"\\x{o:02x}")
        else:
            out.append(ch)
    return "".join(out)


# ------------------------------------------------------------ built-in maps

def _vt100() -> dict[str, str]:
    m = {
        "Up": "\\e[A", "Down": "\\e[B", "Right": "\\e[C", "Left": "\\e[D",
        "app:Up": "\\eOA", "app:Down": "\\eOB", "app:Right": "\\eOC", "app:Left": "\\eOD",
        "F1": "\\eOP", "F2": "\\eOQ", "F3": "\\eOR", "F4": "\\eOS",
        "Backspace": "^?", "Enter": "\\r", "KeypadEnter": "\\r", "Tab": "\\t",
        "Shift+Tab": "\\e[Z", "Escape": "\\e",
        "kp:KeypadEnter": "\\eOM", "kp:KeypadMinus": "\\eOm", "kp:KeypadComma": "\\eOl",
        "kp:KeypadPlus": "\\eOl", "kp:KeypadDecimal": "\\eOn",
    }
    for i in range(10):
        m[f"kp:Keypad{i}"] = "\\eO" + chr(ord("p") + i)
    return m


def _vt220() -> dict[str, str]:
    m = _vt100()
    codes = {5: 15, 6: 17, 7: 18, 8: 19, 9: 20, 10: 21, 11: 23, 12: 24, 13: 25,
             14: 26, 15: 28, 16: 29, 17: 31, 18: 32, 19: 33, 20: 34}
    for f, c in codes.items():
        m[f"F{f}"] = f"\\e[{c}~"
    # PC keyboards have no F13-F20: Shift+F1..F10 stand in for F11..F20.
    for i in range(1, 11):
        m[f"Shift+F{i}"] = m.get(f"F{i + 10}", "")
    m.update({"Home": "\\e[1~", "Insert": "\\e[2~", "Delete": "\\e[3~",
              "End": "\\e[4~", "PageUp": "\\e[5~", "PageDown": "\\e[6~"})
    return m


def _xterm() -> dict[str, str]:
    m = _vt220()
    m.update({"Home": "\\e[H", "End": "\\e[F", "app:Home": "\\eOH", "app:End": "\\eOF",
              "F11": "\\e[23~", "F12": "\\e[24~"})
    for i in range(1, 11):
        m.pop(f"Shift+F{i}", None)
    mods = {"Shift": 2, "Alt": 3, "Alt+Shift": 4, "Ctrl": 5, "Ctrl+Shift": 6,
            "Ctrl+Alt": 7, "Ctrl+Alt+Shift": 8}
    for mod, n in mods.items():
        for key, final in (("Up", "A"), ("Down", "B"), ("Right", "C"), ("Left", "D"),
                           ("Home", "H"), ("End", "F")):
            m[f"{mod}+{key}"] = f"\\e[1;{n}{final}"
        for i, final in zip(range(1, 5), "PQRS"):
            m[f"{mod}+F{i}"] = f"\\e[1;{n}{final}"
        for i, c in {5: 15, 6: 17, 7: 18, 8: 19, 9: 20, 10: 21, 11: 23, 12: 24}.items():
            m[f"{mod}+F{i}"] = f"\\e[{c};{n}~"
        for key, c in (("Insert", 2), ("Delete", 3), ("PageUp", 5), ("PageDown", 6)):
            m[f"{mod}+{key}"] = f"\\e[{c};{n}~"
    return m


def _linux() -> dict[str, str]:
    m = _vt220()
    for i, ch in zip(range(1, 6), "ABCDE"):
        m[f"F{i}"] = f"\\e[[{ch}"
    return m


def _ansi() -> dict[str, str]:
    """SCO console function keys."""
    m = _vt100()
    for i in range(1, 6):
        m.pop(f"F{i}", None)
    letters = "MNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz@[\\]^_`{"
    groups = ["", "Shift+", "Ctrl+", "Ctrl+Shift+"]
    for g, prefix in enumerate(groups):
        for i in range(12):
            ch = letters[g * 12 + i]
            m[f"{prefix}F{i + 1}"] = "\\e[" + ("\\\\" if ch == "\\" else ch)
    m.update({"Home": "\\e[H", "End": "\\e[F", "PageUp": "\\e[I", "PageDown": "\\e[G",
              "Insert": "\\e[L", "Delete": "^?", "Backspace": "^H"})
    return m


def _wyse() -> dict[str, str]:
    m = {
        "Up": "^K", "Down": "^J", "Left": "^H", "Right": "^L", "Home": "^^",
        "Backspace": "^H", "Delete": "^?", "Insert": "\\eq", "Enter": "\\r",
        "KeypadEnter": "\\r", "Tab": "\\t", "Shift+Tab": "\\eI", "Escape": "\\e",
        "PageDown": "\\eK", "PageUp": "\\eJ", "Shift+Home": "\\e{",
    }
    for i in range(16):
        m[f"F{i + 1}"] = "^A" + chr(ord("@") + i) + "\\r"
        m[f"Shift+F{i + 1}"] = "^A" + chr(ord("`") + i) + "\\r"
    return m


def _ibm3270() -> dict[str, str]:
    """PC-style layout for a 3270 keyboard, close to common PC 3270 emulators."""
    m = {
        "Enter": "action:enter", "KeypadEnter": "action:enter",
        "Shift+Enter": "action:newline", "Tab": "action:tab", "Shift+Tab": "action:backtab",
        "Up": "action:up", "Down": "action:down", "Left": "action:left",
        "Right": "action:right", "Home": "action:home", "End": "action:field-end",
        "Backspace": "action:erase", "Delete": "action:delete", "Insert": "action:insert",
        "Ctrl+End": "action:erase-eof", "Ctrl+Delete": "action:erase-input",
        "Escape": "action:reset", "Pause": "action:clear", "Ctrl+Pause": "action:clear",
        "PageUp": "action:pf7", "PageDown": "action:pf8",
        "Alt+F1": "action:pa1", "Alt+F2": "action:pa2", "Alt+F3": "action:pa3",
        "Ctrl+K": "action:palette",
    }
    for i in range(1, 13):
        m[f"F{i}"] = f"action:pf{i}"
        m[f"Shift+F{i}"] = f"action:pf{i + 12}"
    for i in range(13, 25):
        m[f"F{i}"] = f"action:pf{i}"
    return m


def _ibm5250() -> dict[str, str]:
    """PC-style layout for a 5250 keyboard.

    Enter is Enter, as users expect; keypad Enter is Field Exit and keypad
    +/- are Field+/Field-. Escape is Reset, as in the 3270 keymap (operator
    errors need it often); Shift+Escape and Pause are Attention; SysReq
    (Alt+Print) is System Request. PageUp/PageDown roll the screen.
    """
    m = {
        "Enter": "action:enter", "KeypadEnter": "action:field-exit",
        "Shift+Enter": "action:newline", "Tab": "action:tab", "Shift+Tab": "action:backtab",
        "Up": "action:up", "Down": "action:down", "Left": "action:left",
        "Right": "action:right", "Home": "action:home", "End": "action:field-end",
        "Backspace": "action:erase", "Delete": "action:delete", "Insert": "action:insert",
        "Ctrl+End": "action:erase-eof", "Ctrl+Delete": "action:erase-input",
        "KeypadPlus": "action:field-plus", "KeypadMinus": "action:field-minus",
        "Escape": "action:reset", "Shift+Escape": "action:attn", "Pause": "action:attn",
        "SysReq": "action:sysreq", "Alt+Print": "action:sysreq",
        "Ctrl+Pause": "action:clear", "Ctrl+F1": "action:help", "Ctrl+D": "action:dup",
        "Ctrl+Print": "action:print",
        "PageUp": "action:roll-down", "PageDown": "action:roll-up",
        "Ctrl+K": "action:palette",
    }
    for i in range(1, 13):
        m[f"F{i}"] = f"action:f{i}"
        m[f"Shift+F{i}"] = f"action:f{i + 12}"
    for i in range(13, 25):
        m[f"F{i}"] = f"action:f{i}"
    return m


COMMON = {
    "Ctrl+Shift+C": "action:copy",
    "Ctrl+Shift+V": "action:paste",
    "Shift+Insert": "action:paste",
    "Shift+PageUp": "action:scroll-up",
    "Shift+PageDown": "action:scroll-down",
    "Break": "action:break",
    "Print": "action:print-screen",
}

# Mac keyboards have no Insert (extended ones have Help there, which counts
# as Insert), Pause, Print or SysReq key, and laptops have no keypad. On
# macOS the IBM maps add these so every 3270 and 5250 function has a key;
# fn+Return is keypad Enter (5250 Field Exit) on a laptop.
MAC_EXTRA: dict[str, dict[str, str]] = {
    "ibm3270": {"Clear": "action:clear", "Ctrl+Escape": "action:clear",
                "Ctrl+I": "action:insert"},
    "ibm5250": {"Clear": "action:clear", "Ctrl+Escape": "action:sysreq",
                "Ctrl+I": "action:insert", "Ctrl+P": "action:print",
                "Ctrl+=": "action:field-plus", "Ctrl+-": "action:field-minus"},
}

# Windows keeps some keys for itself: Ctrl+Pause arrives as Ctrl+Break, Print
# Screen opens the Snipping Tool on Windows 11 and Alt+Print Screen copies
# the window. The IBM maps add other keys for what those do on Linux.
WINDOWS_EXTRA: dict[str, dict[str, str]] = {
    "ibm3270": {"Ctrl+Break": "action:clear"},
    "ibm5250": {"Ctrl+Break": "action:clear", "Ctrl+P": "action:print",
                "Shift+Pause": "action:sysreq"},
}

BUILTIN: dict[str, dict[str, str]] = {
    "vt100": _vt100(), "vt220": _vt220(), "xterm": _xterm(), "linux": _linux(),
    "ansi": _ansi(), "wyse": _wyse(), "ibm3270": _ibm3270(), "ibm5250": _ibm5250(),
}


# ------------------------------------------------------------------ lookup

@dataclass
class Binding:
    kind: str          # "send" or "action"
    value: str         # characters to send, or the action name

    @classmethod
    def parse(cls, raw: str) -> "Binding":
        if raw.startswith("action:"):
            return cls("action", raw[len("action:"):])
        return cls("send", parse_notation(raw))


@dataclass
class Keymap:
    """A flattened set of bindings, keyed by canonical key name."""

    bindings: dict[str, str] = field(default_factory=dict)

    @classmethod
    def builtin(cls, name: str, mac: bool = IS_MAC, windows: bool = IS_WINDOWS) -> "Keymap":
        if name not in BUILTIN:
            raise ValueError(f"unknown built-in keymap {name!r}")
        km = cls(dict(COMMON))
        km.update(BUILTIN[name])
        if mac:
            km.update(MAC_EXTRA.get(name, {}))
        if windows:
            km.update(WINDOWS_EXTRA.get(name, {}))
        return km

    def update(self, overrides: dict[str, str]) -> None:
        for key, value in overrides.items():
            key = normalize_key(key)
            if value in ("", None):
                # An empty override unbinds the key so it falls back to its text.
                self.bindings.pop(key, None)
            else:
                Binding.parse(value)  # validate early
                self.bindings[key] = value

    def lookup(self, key: str, app_cursor: bool = False, app_keypad: bool = False) -> Binding | None:
        key = normalize_key(key)
        candidates = []
        if app_cursor:
            candidates.append("app:" + key)
        if app_keypad:
            candidates.append("kp:" + key)
        candidates.append(key)
        for k in candidates:
            if k in self.bindings:
                return Binding.parse(self.bindings[k])
        return None

    def key_for(self, action: str) -> str:
        """The key that runs ``action``, for showing beside a button: an
        unmodified key if there is one, else the shortest. "" if none does.
        A 3270 ``pf3`` is also found as the 5250 ``f3``."""
        wanted = {f"action:{action}"}
        if action.startswith("pf") and action[2:].isdigit():
            wanted.add(f"action:f{action[2:]}")
        keys = [k for k, v in self.bindings.items() if v in wanted and ":" not in k]

        def effort(key: str) -> tuple:
            # F13-F24 are missing from most keyboards: Shift+F1 beats F13.
            rare = bool(re.fullmatch(r"F(1[3-9]|2[0-4])", key.split("+")[-1]))
            return key.count("+") + 1.5 * rare, len(key), key
        return min(keys, key=effort, default="")
