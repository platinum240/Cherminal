"""Emulation registry."""

from __future__ import annotations

from .base import Emulation
from .ibm3270 import IBM3270, IBM3278Model3, IBM3278Model4, IBM3278Model5
from .ibm5250 import IBM3477FC, IBM5250, IBM5251
from .ibm3287 import IBM3287
from .vt import AT386, VT100, VT220, VT320, VT420, AnsiSCO, LinuxConsole, Xterm
from .wyse import ADM3A, TVI925, TVI950, Wyse50, Wyse60

EMULATIONS: dict[str, type[Emulation]] = {
    cls.name: cls for cls in (VT100, VT220, VT320, VT420, AnsiSCO, AT386, LinuxConsole,
                              Xterm, Wyse50, Wyse60, TVI925, TVI950, ADM3A,
                              IBM3270, IBM3278Model3, IBM3278Model4, IBM3278Model5,
                              IBM5250, IBM5251, IBM3477FC, IBM3287)
}

# Older names still accepted in saved sessions and on the command line.
ALIASES = {"ansi": "scoansi"}

# Encodings that suit each emulation when a profile does not set one.
DEFAULT_ENCODING = {
    "vt100": "latin-1", "vt220": "latin-1", "scoansi": "cp437", "linux": "utf-8",
    "xterm": "utf-8", "wyse50": "latin-1", "wyse60": "latin-1", "vt320": "latin-1",
    "vt420": "latin-1", "at386": "cp437", "tvi925": "latin-1", "tvi950": "latin-1",
    "adm3a": "ascii",
    # EBCDIC: US/Canada. Hosts in other countries use e.g. cp500, cp273, cp1140.
    "ibm3278-2": "cp037", "ibm3278-3": "cp037", "ibm3278-4": "cp037", "ibm3278-5": "cp037",
    "ibm3179-2": "cp037", "ibm5251-11": "cp037", "ibm3477-fc": "cp037",
    "ibm3287-1": "cp037",
}


def create(name: str, screen, reply=None, encoding: str | None = None,
           answerback: str = "") -> Emulation:
    name = ALIASES.get(name, name)
    try:
        cls = EMULATIONS[name]
    except KeyError:
        raise ValueError(f"unknown emulation {name!r}; choose from {', '.join(EMULATIONS)}")
    return cls(screen, reply, encoding=encoding or DEFAULT_ENCODING[name], answerback=answerback)


__all__ = ["ALIASES", "EMULATIONS", "DEFAULT_ENCODING", "Emulation", "create"]
