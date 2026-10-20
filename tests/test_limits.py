"""A host can't make the parsers hold unbounded data (or loop for ever)."""

import time

from cherminal.emulation.base import MAX_SEQUENCE
from cherminal.emulation.ibm3270 import MAX_RECORD
from cherminal.transport.telnet import IAC, SB, SE, MAX_SUBNEGOTIATION, TelnetProtocol


def test_endless_osc_title_is_capped(term):
    emu, screen, _ = term("xterm")
    emu.feed(b"\x1b]0;" + b"A" * 1_000_000)
    assert len(emu.osc) <= MAX_SEQUENCE
    emu.feed(b"\x07ok")
    assert screen.title == "A" * (MAX_SEQUENCE - len("0;"))
    assert screen.line_text(0).startswith("ok")


def test_endless_csi_is_dropped(term):
    emu, screen, _ = term("vt220")
    emu.feed(b"\x1b[" + b"1;" * 100_000)
    assert len(emu.params) <= MAX_SEQUENCE
    emu.feed(b"\x1b[Hok")
    assert screen.line_text(0).startswith("ok")


def test_huge_counts_are_clamped(term):
    emu, screen, _ = term("vt220")
    start = time.monotonic()
    emu.feed(b"x\x1b[" + b"9" * 4000 + b"b")     # REP
    emu.feed(b"\x1b[999999999I\x1b[999999999Z")  # tab forward / back
    emu.feed(b"\x1b[999999999@\x1b[999999999P")  # insert / delete characters
    assert time.monotonic() - start < 2
    assert all(len(line) == screen.cols for line in screen.lines)


def test_endless_wyse_sequence_is_dropped(term):
    emu, screen, _ = term("wyse60")
    emu.feed(b"\x1bf" + b"A" * 100_000)          # ESC f <text> CR: status line text
    assert emu._seq is None or len(emu._seq) <= MAX_SEQUENCE


def test_oversized_3270_record_is_dropped(term):
    emu, screen, _ = term("ibm3278-2")
    emu.feed(b"\xf5\xc3" + b"\x40" * (MAX_RECORD + 10))
    assert len(emu._rec) <= MAX_RECORD
    emu.feed(bytes([IAC, 0xEF]))                 # EOR
    assert emu._rec == b"" and not emu._rec_dropped


def test_vt_print_job_is_sent_in_pieces(term):
    emu, screen, _ = term("vt220")
    emu.MAX_PRINT_CHUNK = 1000
    jobs = []
    emu.on_print_data = jobs.append
    emu.feed(b"\x1b[5i")
    for _ in range(25):
        emu.feed(b"P" * 100)                     # as it arrives from the host
    emu.feed(b"\x1b[4i")
    assert b"".join(jobs) == b"P" * 2500
    assert len(jobs) == 3 and max(len(j) for j in jobs) <= 1000


def test_telnet_subnegotiation_is_capped():
    proto = TelnetProtocol(lambda data: None, "VT220")
    proto.receive(bytes([IAC, SB]) + b"\x18" * 100_000)
    assert len(proto._sb) <= MAX_SUBNEGOTIATION
    proto.receive(bytes([IAC, SE]) + b"ok")
