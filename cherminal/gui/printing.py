"""Printing on the workstation: Print Screen and host passthrough jobs."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QFont, QFontMetricsF, QPainter, QPageLayout
from PyQt6.QtPrintSupport import QAbstractPrintDialog, QPrintDialog, QPrinter, QPrinterInfo
from PyQt6.QtWidgets import QMessageBox

from .. import system


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
        # A form feed in the text starts a new page; long pages run over.
        forms: list[list[str]] = [[]]
        for line in lines:
            parts = line.split("\f")
            forms[-1].append(parts[0])
            forms += [[part] for part in parts[1:]]
        pages = [form[i:i + per_page] for form in forms
                 for i in range(0, max(1, len(form)), per_page)]
        for n, page_lines in enumerate(pages):
            if n:
                printer.newPage()
            p.setPen(Qt.GlobalColor.black)
            p.setFont(head)
            band = QRectF(0, 0, page.width(), hm.height())
            p.drawText(band, Qt.AlignmentFlag.AlignLeft, title)
            p.drawText(band, Qt.AlignmentFlag.AlignRight, stamp)
            p.setFont(font)
            y = top + fm.ascent()
            for line in page_lines:
                p.drawText(0, int(y), line)
                y += fm.lineSpacing()
    finally:
        p.end()


def to_file(printer: QPrinter) -> bool:
    """True if the printer writes a file (PDF) rather than going to a printer."""
    return (printer.outputFormat() != QPrinter.OutputFormat.NativeFormat
            or bool(printer.outputFileName()))


def print_screen(term, parent=None, allow_file: bool = True) -> bool:
    """Print what is on the screen. With a printer set in the session, print
    straight to it; otherwise ask, which also offers printing to a PDF file
    unless ``allow_file`` is off (limited mode, or the site policy)."""
    profile = term.session.profile
    printer = make_printer(profile.printer)
    if not profile.printer or not printer.isValid() or (to_file(printer) and not allow_file):
        if not allow_file and not printer_names():
            QMessageBox.warning(parent, "Print screen", "No printer is set up on this computer.")
            return False
        dlg = QPrintDialog(printer, parent)
        dlg.setWindowTitle("Print screen")
        dlg.setOption(QAbstractPrintDialog.PrintDialogOption.PrintToFile, allow_file)
        if not dlg.exec():
            return False
        if to_file(printer) and not allow_file:
            QMessageBox.warning(parent, "Print screen",
                                "Printing to a file is not allowed on this computer.")
            return False
    render(printer, screen_lines(term), profile.name, system.font_family(profile.font_family))
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
    if not printer.isValid() or to_file(printer):
        QMessageBox.warning(parent, "Print", "The host sent a print job, but no printer "
                                             "is set up on this machine.")
        return "Print job dropped: no printer"
    text = data.decode("latin-1").replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")
    render(printer, text.split("\n"), "Host print job", system.font_family(""))
    return f"Printed a host print job on {printer.printerName()}"


def print_text(text: str, printer_name: str, title: str = "Host print job") -> str:
    """Print a decoded host job (a 3287 printer session) without asking
    anything: through CUPS's lp, which lays out plain text itself, or else
    with Qt on the session's printer or the default one. Returns a status
    line; failures are reported there, never in a dialog."""
    lp = shutil.which("lp")
    if lp:
        cmd = [lp, "-s", "-t", title] + (["-d", printer_name] if printer_name else [])
        try:
            subprocess.run(cmd, input=text.encode("utf-8"), check=True, timeout=60,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            return f"Printed {title} on {printer_name or 'the default printer'}"
        except (OSError, subprocess.SubprocessError) as e:
            err = getattr(e, "stderr", b"") or b""
            return f"Print job failed: {err.decode(errors='replace').strip() or e}"
    name = printer_name or QPrinterInfo.defaultPrinterName()
    printer = make_printer(name)
    if not name or not printer.isValid() or to_file(printer):
        return "Print job dropped: no printer is set up on this machine"
    render(printer, text.rstrip("\n").split("\n"), title, system.font_family(""))
    return f"Printed {title} on {printer.printerName()}"
