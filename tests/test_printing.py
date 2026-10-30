import os
import shutil
import subprocess
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

from cherminal.config import ProfileStore, SessionProfile  # noqa: E402
from cherminal.session import Session  # noqa: E402

JOB = b"\x1bE\x00\xff report \x1b&l1O\x0c"


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def session(tmp_path, **kw):
    return Session(SessionProfile(**kw), ProfileStore(tmp_path, site_roots=[]))


@pytest.mark.parametrize("split", range(0, 40))
def test_passthrough_job_is_cut_out_byte_exact(tmp_path, split):
    s = session(tmp_path, emulation="vt220")
    jobs = []
    s.emulation.on_print_data = jobs.append
    data = b"before\x1b[5i" + JOB + b"\x1b[4iafter"
    s.feed(data[:split])
    s.feed(data[split:])
    assert jobs == [JOB]
    assert s.screen.line_text(0) == "beforeafter"


def test_passthrough_off_shows_nothing_to_printer(tmp_path):
    s = session(tmp_path, emulation="vt220", host_print=False)
    jobs = []
    s.emulation.on_print_data = jobs.append
    s.feed(b"a\x1b[5ib\x1b[4ic")
    assert jobs == [] and s.screen.line_text(0) == "abc"


def test_print_key_runs_print_screen(tmp_path):
    for emu, transport in (("vt220", "ssh"), ("ibm3278-2", "telnet")):
        s = session(tmp_path, emulation=emu, transport=transport)
        actions = []
        s.on_action = actions.append
        assert s.key("Print")
        assert actions == ["print-screen"], emu


def test_render_to_pdf(app, tmp_path):
    from PyQt6.QtPrintSupport import QPrinter

    from cherminal.gui.printing import render, screen_lines
    from cherminal.gui.terminal import TerminalWidget
    term = TerminalWidget(session(tmp_path))
    term.session.feed(b"USERID ===> USERNAME\r\nPASSWORD ===> \x1b[8msecret\x1b[0m\r\n")
    lines = screen_lines(term)
    assert lines[:2] == ["USERID ===> USERNAME", "PASSWORD ===>"]       # hidden field blank
    printer = QPrinter()
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    out = tmp_path / "screen.pdf"
    printer.setOutputFileName(str(out))
    render(printer, lines + [f"row {i}" for i in range(200)], "Mainframe", "Monospace")
    assert out.read_bytes().startswith(b"%PDF")
    if shutil.which("pdftotext"):
        text = subprocess.run(["pdftotext", str(out), "-"], capture_output=True,
                              text=True).stdout
        assert "USERID ===> USERNAME" in text and "secret" not in text
        assert "\f" in text.rstrip("\f")                            # ran onto a second page


@pytest.mark.skipif(sys.platform == "win32", reason="CUPS lp; Windows uses the spooler")
def test_print_raw_uses_lp(app, tmp_path, monkeypatch):
    from cherminal.gui.printing import print_raw
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "lp").write_text(f'#!/bin/sh\necho "$@" > {tmp_path}/args\ncat > {tmp_path}/job\n')
    (bin_dir / "lp").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    assert "front-desk" in print_raw(JOB, "front-desk")
    assert (tmp_path / "job").read_bytes() == JOB
    assert (tmp_path / "args").read_text().split() == ["-o", "raw", "-s", "-d", "front-desk"]


def test_editor_printing_tab(app, tmp_path):
    from cherminal.gui.dialogs import SessionEditor
    store = ProfileStore(tmp_path, site_roots=[])
    ed = SessionEditor(SessionProfile(name="s", host="h", printer="front-desk",
                                      host_print=False), store)
    p = ed._build()
    assert p.printer == "front-desk" and not p.host_print
    ed.printer.setCurrentIndex(0)
    assert ed._build().printer == ""
    ed.printer.setEditText("laser-2")
    assert ed._build().printer == "laser-2"
    assert SessionProfile().to_dict().get("printer") is None


def test_print_menu_items(app, tmp_path, monkeypatch):
    from cherminal import system
    from cherminal.gui.app import MainWindow
    monkeypatch.setattr(system, "IS_MAC", False)       # Linux shortcuts (Mac: test_macos)
    win = MainWindow(ProfileStore(tmp_path, site_roots=[]), limited=True)
    session_menu = [a for a in win.menuBar().actions() if a.text() == "&Session"][0].menu()
    acts = {a.text(): a.shortcut().toString() for a in session_menu.actions()}
    assert acts["&Print screen…"] == "Ctrl+Shift+P"
