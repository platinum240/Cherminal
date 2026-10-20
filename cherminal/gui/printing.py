"""Printing on the workstation: Print Screen and host passthrough jobs."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QFont, QFontMetricsF, QPainter, QPageLayout
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter, QPrinterInfo
from PyQt6.QtWidgets import QMessageBox


def printer_names() -> list[str]:
    return list(QPrinterInfo.availablePrinterNames())


def make_printer(name: str) -> QPrinter:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    if name:
        printer.setPrinterName(name)
    return printer


def screen_lines(term) -> list[str]:
    """The screen as the user sees it, with hidden fields left blank."""
    with term.session.lock:
        return [term._line_text(line).rstrip() for line in term.session.screen.lines]


def render(printer: QPrinter, lines: list[str], title: str, family: str) -> None:
    """A small heading, then the lines in a monospaced font sized (10pt at
    most) so the widest line fits the page width; long jobs run over pages."""
    cols = max([80] + [len(line) for line in lines])
    if cols > 100:
        printer.setPageOrientation(QPageLayout.Orientation.Landscape)
    p = QPainter(printer)
    try:
        page = QRectF(p.viewport())
        head = QFont(family)
        head.setPointSizeF(8)
        hm = QFontMetricsF(head, printer)
        font = QFont(family)
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        font.setFixedPitch(True)
        font.setPointSizeF(10)
        fm = QFontMetricsF(font, printer)
        scale = min(page.width() / (cols * fm.horizontalAdvance("M")), 1.0)
        font.setPointSizeF(max(4.0, 10 * scale))
        fm = QFontMetricsF(font, printer)
        top = hm.height() * 2
        per_page = max(1, int((page.height() - top) // fm.lineSpacing()))
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        for start in range(0, max(1, len(lines)), per_page):
            if start:
                printer.newPage()
            p.setPen(Qt.GlobalColor.black)
            p.setFont(head)
            band = QRectF(0, 0, page.width(), hm.height())
            p.drawText(band, Qt.AlignmentFlag.AlignLeft, title)
            p.drawText(band, Qt.AlignmentFlag.AlignRight, stamp)
            p.setFont(font)
            y = top + fm.ascent()
            for line in lines[start:start + per_page]:
                p.drawText(0, int(y), line)
                y += fm.lineSpacing()
    finally:
        p.end()


def print_screen(term, parent=None) -> bool:
    """Print what is on the screen. With a printer set in the session, print
    straight to it; otherwise ask, which also offers printing to a PDF file."""
    profile = term.session.profile
    printer = make_printer(profile.printer)
    if not profile.printer or not printer.isValid():
        dlg = QPrintDialog(printer, parent)
        dlg.setWindowTitle("Print screen")
        if not dlg.exec():
            return False
    render(printer, screen_lines(term), profile.name, profile.font_family or "Monospace")
    return True


def print_raw(data: bytes, printer_name: str, parent=None) -> str:
    """Send a host's passthrough job to the printer untouched, as a terminal
    printer port would. Returns a status line for the user."""
    lp = shutil.which("lp")
    if lp:
        cmd = [lp, "-o", "raw", "-s"]
        name = printer_name or ""
        if name:
            cmd += ["-d", name]
        try:
            subprocess.run(cmd, input=data, check=True, timeout=60,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            return f"Sent a {len(data)} byte print job to {name or 'the default printer'}"
        except (OSError, subprocess.SubprocessError) as e:
            err = getattr(e, "stderr", b"") or b""
            reason = err.decode(errors="replace").strip() or str(e)
            QMessageBox.warning(parent, "Print", f"The host's print job failed: {reason}")
            return "Print job failed"
    # No CUPS command line: print the job as plain text through Qt instead.
    printer = make_printer(printer_name)
    if not printer.isValid():
        QMessageBox.warning(parent, "Print", "The host sent a print job, but no printer "
                                             "is set up on this machine.")
        return "Print job dropped: no printer"
    text = data.decode("latin-1").replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")
    render(printer, text.split("\n"), "Host print job", "Monospace")
    return f"Printed a host print job on {printer.printerName()}"
