"""Read TinyTERM (Century Software) ``.tpx`` session files.

A ``.tpx`` file is a Windows INI file: ``[term.emu]`` (emulation, screen,
colours), ``[term.comm]`` (host, port, serial line), ``[term.ft]`` (file
transfer), ``[term.gen]`` (window and toolbars) and more. Section names are
``[TERM.emu]`` or ``[term.emu]`` depending on the TinyTERM version. Most of
the several hundred keys are TinyTERM's own (toolbar buttons, Windows
printers, window position, its bitmap fonts); this module takes the ones
that have a Cherminal equivalent and reports the rest that matter.

Value codes come from Century Software's documentation: the emulation
numbers are the TE control's "Emulation (Get Value)" table and the colours
its 1-16 colour table (CScript Object Reference: TE Control), and the extra
keys from "TPX File Settings". The connection type codes are not documented;
``commtype=5`` is Telnet in every file seen (they also say ``cdelay=TELNET``).

``read(path)`` returns a :class:`SessionProfile` and a list of notes (things
that were not or could not be carried over) for the person importing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import system
from .config import SessionProfile

SUFFIX = ".tpx"

# emulate=N -> (Cherminal emulation, TinyTERM's name). None: no equivalent.
EMULATIONS: dict[int, tuple[str | None, str]] = {
    1: ("vt320", "VT320"),
    2: ("vt320", "VT320-7"),
    3: ("vt220", "VT220"),
    4: ("vt220", "VT220-7"),
    5: ("vt100", "VT100/VT102"),
    7: ("scoansi", "ANSI"),
    8: ("at386", "AT386"),
    9: ("scoansi", "SCO ANSI"),
    10: ("wyse60", "Wyse 60"),
    11: ("wyse60", "Wyse 60-25"),
    12: (None, "PC Term"),
    13: ("tvi950", "TeleVideo 950"),
    14: ("wyse50", "Wyse 50"),
    15: ("tvi925", "TeleVideo 925"),
    16: ("tvi925", "TeleVideo 912"),
    17: (None, "ADM-1"),
    18: (None, "IBM 3101"),
    19: (None, "IBM 3151"),
    20: (None, "IBM 3151-25"),
    22: ("ibm3477-fc", "IBM 3477"),
    23: ("ibm3278-2", "IBM 3278-2"),
    24: ("ibm3278-3", "IBM 3278-3"),
    25: ("ibm3278-4", "IBM 3278-4"),
    26: ("ibm3278-5", "IBM 3278-5"),
}
# What to use when TinyTERM's emulation has no Cherminal equivalent.
FALLBACK = {"PC Term": "scoansi"}
DEFAULT_FALLBACK = "vt220"

# TinyTERM's colour numbers 1-16 (0 = the default for the attribute): the
# sixteen PC colours in TinyTERM's order.
COLOURS = {
    1: "#000000", 2: "#0000aa", 3: "#00aa00", 4: "#00aaaa",
    5: "#aa0000", 6: "#aa00aa", 7: "#aa5500", 8: "#aaaaaa",
    9: "#555555", 10: "#5555ff", 11: "#55ff55", 12: "#55ffff",
    13: "#ff5555", 14: "#ff55ff", 15: "#ffff55", 16: "#ffffff",
}

COMM_TELNET = 5
COMM_SERIAL = 0
PARITY = {0: "none", 1: "odd", 2: "even", 3: "mark", 4: "space"}
STOP_BITS = {0: 1, 1: 1.5, 2: 2}
LINE_ENDS = {"\\r": "cr", "\\r\\n": "crlf", "\\n": "lf"}


@dataclass
class TpxFile:
    """The parsed file: lower-cased section -> key -> value (keys keep their case)."""
    sections: dict[str, dict[str, str]] = field(default_factory=dict)

    def get(self, section: str, key: str, default: str = "") -> str:
        values = self.sections.get(section, {})
        if key in values:
            return values[key]
        lowered = {k.lower(): v for k, v in values.items()}
        return lowered.get(key.lower(), default)

    def int(self, section: str, key: str, default: int = 0) -> int:
        try:
            return int(self.get(section, key, str(default)).strip())
        except ValueError:
            return default


def parse(text: str) -> TpxFile:
    """Parse INI text. Not configparser: values hold ``%``, ``;``, ``#`` and
    trailing spaces that matter (``stpsvrW1=$  ``), and keys repeat."""
    tpx = TpxFile()
    section = tpx.sections.setdefault("", {})
    for raw in text.splitlines():
        line = raw.rstrip("\r\n")
        if line.startswith("[") and line.rstrip().endswith("]"):
            section = tpx.sections.setdefault(line.strip()[1:-1].lower(), {})
        elif "=" in line:
            key, value = line.split("=", 1)
            section[key.strip()] = value
    return tpx


def hosts(tpx: TpxFile) -> list[str]:
    """The host names in ``node``: TinyTERM keeps its host box's history
    there, most recent (the one it connects to) first."""
    out = []
    for entry in tpx.get("term.comm", "node").split("|"):
        entry = re.sub(r"^[a-z]+://", "", entry.strip(), flags=re.I).strip("/")
        if entry and entry not in out:
            out.append(entry)
    return out


def _encoding(name: str) -> str:
    """TinyTERM code page names ("STD 437 MS-DOS Latin US",
    "1252 Windows Latin 1 (ANSI)") -> a Python codec, or ""."""
    m = re.search(r"\b(437|737|775|850|852|855|857|860|861|862|863|864|865|866|869|"
                  r"1250|1251|1252|1253|1254|1255|1256|1257|1258)\b", name)
    if m:
        return f"cp{m.group(1)}"
    m = re.search(r"8859-(\d+)", name)
    return f"iso8859-{m.group(1)}" if m else ""


def _serial_device(port: int) -> str:
    if system.IS_WINDOWS:
        return f"COM{port}"
    if system.IS_MAC:
        return system.default_serial_device()
    return f"/dev/ttyS{max(port - 1, 0)}"


def to_profile(tpx: TpxFile, name: str) -> tuple[SessionProfile, list[str]]:
    notes: list[str] = []
    emu, comm = "term.emu", "term.comm"
    data: dict = {"name": name}

    code = tpx.int(emu, "emulate", 9)
    mapped, tt_name = EMULATIONS.get(code, (None, f"emulation {code}"))
    if mapped is None:
        mapped = FALLBACK.get(tt_name, DEFAULT_FALLBACK)
        notes.append(f"TinyTERM's {tt_name} emulation has no exact equivalent; "
                     f"set to {mapped}, check the screen and keys")
    data["emulation"] = mapped
    block_mode = mapped.startswith("ibm")

    # ---------------------------------------------------------- connection
    names = hosts(tpx)
    commtype = tpx.int(comm, "commtype", COMM_TELNET)
    if commtype == COMM_SERIAL and not names:
        port = tpx.int(comm, "ComPort", 1)
        data.update(transport="serial", serial_device=_serial_device(port),
                    baud=tpx.int(comm, "baud", 9600),
                    data_bits=tpx.int(comm, "wordlen", 8),
                    parity=PARITY.get(tpx.int(comm, "parity"), "none"),
                    stop_bits=STOP_BITS.get(tpx.int(comm, "stopbits"), 1),
                    flow_control="rtscts" if tpx.int(emu, "rtscts") else "none")
        notes.append(f"serial port COM{port} became {data['serial_device']}; "
                     "change it if the device is elsewhere")
    else:
        if commtype != COMM_TELNET:
            notes.append(f"connection type {commtype} is not one Cherminal knows from "
                         "TinyTERM; imported as Telnet, check it")
        data["transport"] = "telnet"
        if names:
            data["host"] = names[0]
            if len(names) > 1:
                notes.append("TinyTERM also lists " + ", ".join(names[1:]))
        else:
            notes.append("no host name in the file; add one before connecting")
        port = tpx.int(comm, "port", 23)
        if port != 23:
            data["port"] = port
        keepalive = tpx.int(comm, "telnetkeepalive")
        if keepalive > 0:
            data["keepalive"] = keepalive

    # -------------------------------------------------------------- screen
    if not block_mode:
        cols, rows = tpx.int(emu, "col", 80), tpx.int(emu, "lines", 24)
        if 20 <= cols <= 500:
            data["cols"] = cols
        if 5 <= rows <= 200:
            data["rows"] = rows
    scrollback = tpx.int(emu, "scrollback")
    if scrollback > 0:
        data["scrollback"] = scrollback
    fg, bg = tpx.int(emu, "colorfg0"), tpx.int(emu, "colorbg0")
    if not block_mode and fg in COLOURS and bg in COLOURS:
        data["fg_color"], data["bg_color"] = COLOURS[fg], COLOURS[bg]

    encoding = _encoding(tpx.get(emu, "cptrxin"))
    if encoding and not block_mode:
        data["encoding"] = encoding

    # ------------------------------------------------------------ keyboard
    if not block_mode:
        data["backspace"] = "del" if tpx.int(emu, "bsdel") else "bs"
        data["enter_sends"] = "crlf" if tpx.int(emu, "addlf") else "cr"
        answerback = tpx.get(emu, "wru")
        if answerback:
            data["answerback"] = answerback
    user = tpx.get(emu, "user").strip()
    if user:
        data["username"] = user
    if tpx.get(emu, "password").strip():
        notes.append("the saved password was not imported; Cherminal never stores passwords")
    if tpx.int(emu, "login"):
        notes.append("TinyTERM's automatic login script was not imported")
    keymap_file = tpx.get(emu, "KeymapFile") or tpx.get(emu, "keyboardfile")
    if keymap_file.strip():
        notes.append(f"keyboard file {keymap_file.strip()} was not imported; "
                     "remap keys with cherminal-keycapture or the keyboard editor")
    return SessionProfile.from_dict(data), notes


def read(path: Path | str, name: str | None = None) -> tuple[SessionProfile, list[str]]:
    """Load a ``.tpx`` file; the session is named after the file."""
    path = Path(path)
    text = path.read_bytes().decode("cp1252", errors="replace")
    tpx = parse(text)
    if "term.emu" not in tpx.sections and "term.comm" not in tpx.sections:
        raise ValueError(f"{path.name} is not a TinyTERM session file")
    return to_profile(tpx, name or path.stem)


def is_tpx(path: str | Path) -> bool:
    return str(path).lower().endswith(SUFFIX)
