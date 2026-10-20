"""The IND$FILE "Transfer file" dialog for 3270 sessions."""

from __future__ import annotations

import os

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog,
                             QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                             QMessageBox, QProgressBar, QPushButton, QRadioButton, QSpinBox,
                             QVBoxLayout, QWidget)

from .. import policy
from ..emulation.indfile import TransferOptions
from ..session import transfer_folder

HOST_HINTS = {"tso": "'USERID.DATA.SET' or 'USERID.PDS(MEMBER)'", "cics": "FILENAME",
              "vm": "FNAME FTYPE A"}


class _Bridge(QObject):
    progress = pyqtSignal(int, int)
    done = pyqtSignal(bool, str)


class TransferDialog(QDialog):
    """Send a file to the host or receive one, with progress and Cancel."""

    def __init__(self, term, limited: bool = False, parent=None):
        super().__init__(parent)
        self.term, self.session = term, term.session
        # Limited: no file browser; files live directly in the Downloads folder.
        self.limited = limited or policy.current().limited
        self.running = False
        self.setWindowTitle("Transfer file")
        rules = policy.current()
        self.can_send = rules.file_transfer(True, limited)
        self.can_receive = rules.file_transfer(False, limited)

        self.send = QRadioButton("Send to the host (PUT)")
        self.receive = QRadioButton("Receive from the host (GET)")
        direction = QButtonGroup(self)
        for b in (self.send, self.receive):
            direction.addButton(b)
        self.send.setEnabled(self.can_send)
        self.receive.setEnabled(self.can_receive)
        (self.receive if self.can_receive else self.send).setChecked(True)
        self.host_type = QComboBox()
        for label, value in (("TSO (z/OS)", "tso"), ("CICS", "cics"), ("VM/CMS", "vm")):
            self.host_type.addItem(label, value)
        self.host_file = QLineEdit()
        self.local_file = QLineEdit()
        local_row = QHBoxLayout()
        if self.limited:
            self.local_file = QComboBox(editable=True)
            local_row.addWidget(self.local_file, 1)
            local_row.addWidget(QLabel(f"in {transfer_folder()}"))
        else:
            local_row.addWidget(self.local_file, 1)
            browse = QPushButton("Browse…")
            browse.clicked.connect(self._browse)
            local_row.addWidget(browse)
        self.text_mode = QRadioButton("Text (ASCII, code page translated)")
        self.binary = QRadioButton("Binary (bytes unchanged)")
        mode = QButtonGroup(self)
        mode.addButton(self.text_mode)
        mode.addButton(self.binary)
        self.text_mode.setChecked(True)
        self.crlf = QCheckBox("Records end in CR LF (CRLF)")
        self.crlf.setChecked(True)
        self.append = QCheckBox("Append to the existing file (APPEND)")

        self.alloc = QGroupBox("New data set on the host")
        af = QFormLayout(self.alloc)
        self.recfm = QComboBox()
        for label, value in (("host default", ""), ("F (fixed)", "F"), ("V (variable)", "V"),
                             ("U (undefined)", "U")):
            self.recfm.addItem(label, value)
        self.lrecl = QSpinBox(maximum=32760, specialValueText="default")
        self.blksize = QSpinBox(maximum=32760, specialValueText="default")
        self.units = QComboBox()
        for label, value in (("host default", ""), ("tracks", "tracks"),
                             ("cylinders", "cylinders"), ("blocks (AVBLOCK)", "avblock")):
            self.units.addItem(label, value)
        self.primary = QSpinBox(maximum=99999)
        self.secondary = QSpinBox(maximum=99999)
        self.avblock = QSpinBox(maximum=32760)
        space = QHBoxLayout()
        for label, w in (("primary", self.primary), ("secondary", self.secondary),
                         ("block size", self.avblock)):
            space.addWidget(QLabel(label))
            space.addWidget(w)
        af.addRow("Record format", self.recfm)
        af.addRow("Record length (LRECL)", self.lrecl)
        self.blksize_label = QLabel("Block size (BLKSIZE)")
        af.addRow(self.blksize_label, self.blksize)
        self.units_label = QLabel("Space")
        af.addRow(self.units_label, self.units)
        self.space_row = QWidget()
        self.space_row.setLayout(space)
        space.setContentsMargins(0, 0, 0, 0)
        af.addRow("", self.space_row)

        self.preview = QLabel()
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.preview.setWordWrap(True)
        self.status = QLabel("Go to a TSO READY prompt (or ISPF option 6), a clear CICS "
                             "screen or the CMS command line first.")
        self.status.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setVisible(False)

        form = QFormLayout()
        dir_row = QVBoxLayout()
        dir_row.addWidget(self.send)
        dir_row.addWidget(self.receive)
        form.addRow("Direction", dir_row)
        form.addRow("Host system", self.host_type)
        form.addRow("Host file", self.host_file)
        form.addRow("Local file", local_row)
        mode_row = QVBoxLayout()
        for w in (self.text_mode, self.binary, self.crlf, self.append):
            mode_row.addWidget(w)
        form.addRow("Transfer", mode_row)
        self.start_button = QPushButton("Transfer")
        self.start_button.setDefault(True)
        self.start_button.clicked.connect(self.start)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self._close_or_cancel)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.close_button)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.alloc)
        lay.addWidget(self.preview)
        lay.addWidget(self.status)
        lay.addWidget(self.bar)
        lay.addLayout(buttons)

        for sig in (self.send.toggled, self.text_mode.toggled, self.append.toggled,
                    self.crlf.toggled):
            sig.connect(self._update)
        for sig in (self.host_type.currentIndexChanged, self.recfm.currentIndexChanged,
                    self.units.currentIndexChanged):
            sig.connect(self._update)
        for w in (self.lrecl, self.blksize, self.primary, self.secondary, self.avblock):
            w.valueChanged.connect(self._update)
        self.host_file.textChanged.connect(self._update)
        self.bridge = _Bridge()
        self.bridge.progress.connect(self._on_progress)
        self.bridge.done.connect(self._on_done)
        self._update()
        self.resize(520, 0)

    # ------------------------------------------------------------ the form

    def _local(self) -> str:
        if self.limited:
            name = self.local_file.currentText().strip()
            return str(transfer_folder() / name) if name else ""
        return os.path.expanduser(self.local_file.text().strip())

    def _browse(self) -> None:
        if self.send.isChecked():
            path, _ = QFileDialog.getOpenFileName(self, "File to send")
        else:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save as", options=QFileDialog.Option.DontConfirmOverwrite)
        if path:
            self.local_file.setText(path)

    def _update(self, *_) -> None:
        send = self.send.isChecked()
        host = self.host_type.currentData()
        self.host_file.setPlaceholderText(HOST_HINTS[host])
        self.crlf.setEnabled(self.text_mode.isChecked())
        self.alloc.setVisible(send and host in ("tso", "vm"))
        tso = host == "tso"
        for w in (self.blksize, self.blksize_label, self.units, self.units_label,
                  self.space_row):
            w.setVisible(tso)
        self.avblock.setEnabled(self.units.currentData() == "avblock")
        if self.limited:
            current = self.local_file.currentText()
            self.local_file.clear()
            folder = transfer_folder()
            if send and folder.is_dir():
                self.local_file.addItems(sorted(p.name for p in folder.iterdir()
                                                if p.is_file() and not p.name.startswith(".")))
            self.local_file.setEditText(current)
        try:
            self.preview.setText("Command: " + self.options().command())
        except ValueError:
            self.preview.setText("Command: IND$FILE …")
        self.adjustSize()

    def options(self) -> TransferOptions:
        return TransferOptions(
            send=self.send.isChecked(), host_file=self.host_file.text(),
            local_file=self._local() or "-", host=self.host_type.currentData(),
            ascii=self.text_mode.isChecked(), crlf=self.crlf.isChecked(),
            append=self.append.isChecked(), recfm=self.recfm.currentData(),
            lrecl=self.lrecl.value(), blksize=self.blksize.value(),
            space_units=self.units.currentData(), primary=self.primary.value(),
            secondary=self.secondary.value(), avblock=self.avblock.value())

    # ------------------------------------------------------------- running

    def start(self) -> None:
        try:
            if not self._local():
                raise ValueError("choose the local file")
            opts = self.options()
        except ValueError as e:
            QMessageBox.warning(self, "Transfer file", str(e).capitalize())
            return
        if self.limited and os.sep in (self.local_file.currentText().strip() or ""):
            QMessageBox.warning(self, "Transfer file", "Give a file name only, not a folder.")
            return
        if opts.send and not os.path.isfile(opts.local_file):
            QMessageBox.warning(self, "Transfer file", f"{opts.local_file} is not a file.")
            return
        if not opts.send and not opts.append and os.path.exists(opts.local_file):
            if QMessageBox.question(self, "Transfer file",
                                    f"{opts.local_file} already exists. Replace it?") \
                    != QMessageBox.StandardButton.Yes:
                return
        try:
            self.session.start_transfer(opts, limited=self.limited,
                                        on_progress=self.bridge.progress.emit,
                                        on_done=self.bridge.done.emit)
        except (ValueError, OSError) as e:      # PolicyError is a ValueError
            QMessageBox.warning(self, "Transfer file", f"Cannot start the transfer: {e}")
            return
        self.term._on_update()
        self.running = True
        self.start_button.setEnabled(False)
        self.close_button.setText("Cancel")
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)                  # busy until the host starts
        self.status.setText(f"Waiting for the host to start: {opts.command()}")

    def _on_progress(self, done: int, total: int) -> None:
        if not self.running:
            return
        if total:
            self.bar.setRange(0, 1000)
            self.bar.setValue(done * 1000 // total)
            self.status.setText(f"Sent {done:,} of {total:,} bytes")
        else:
            self.status.setText(f"Received {done:,} bytes")

    def _on_done(self, ok: bool, message: str) -> None:
        self.running = False
        self.start_button.setEnabled(True)
        self.close_button.setText("Close")
        self.bar.setRange(0, 1000)
        self.bar.setValue(1000 if ok else 0)
        self.status.setText(("Done: " if ok else "Failed: ") + message)
        self.term.message.emit(f"File transfer: {message}")
        self.term._on_update()

    def _close_or_cancel(self) -> None:
        if self.running:
            self.status.setText("Cancelling…")
            self.session.cancel_transfer()
            return
        self.accept()

    def reject(self) -> None:                     # Esc / window close
        if self.running:
            self._close_or_cancel()
        else:
            super().reject()
