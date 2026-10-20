"""TN3270E record headers (RFC 2355), shared by the 3270 display and 3287 printer.

Once the Telnet layer has agreed TN3270E, every record each way starts with
a 5-byte header: data type, request flag, response flag and a sequence
number. A host record marked ALWAYS-RESPONSE is answered with a positive
response (DEVICE-END) once it has been processed.
"""

from __future__ import annotations

from typing import Callable

DT_3270_DATA, DT_SCS_DATA, DT_RESPONSE, DT_BIND_IMAGE, DT_UNBIND, DT_NVT_DATA, \
    DT_REQUEST, DT_SSCP_LU_DATA, DT_PRINT_EOJ = range(9)
RSF_NO_RESPONSE, RSF_ERROR_RESPONSE, RSF_ALWAYS_RESPONSE = range(3)
RSF_POSITIVE, POS_DEVICE_END = 0x00, 0x00
F_RESPONSES = 2


class Framing:
    """Adds and strips headers; ``send`` writes one record to the host."""

    def __init__(self, send: Callable[[bytes], None]):
        self.send = send
        self.active = False
        self.functions: tuple[int, ...] = ()
        self.seq = 0                      # our sequence number (with RESPONSES)
        self.due: bytes | None = None     # host sequence number still to answer

    def start(self, functions: tuple[int, ...]) -> None:
        self.active, self.functions, self.seq, self.due = True, tuple(functions), 0, None

    def split(self, rec: bytes) -> tuple[int, bytes] | None:
        """(data type, data) of a host record; notes a response it wants."""
        if len(rec) < 5:
            return None
        if rec[2] == RSF_ALWAYS_RESPONSE and rec[0] in (DT_3270_DATA, DT_SCS_DATA):
            self.due = rec[3:5]
        return rec[0], rec[5:]

    def ack(self) -> None:
        """Send the positive response the last host record asked for, if any."""
        if self.due is not None:
            due, self.due = self.due, None
            self.send(bytes([DT_RESPONSE, 0, RSF_POSITIVE]) + due + bytes([POS_DEVICE_END]))

    def wrap(self, data: bytes, dtype: int = DT_3270_DATA) -> bytes:
        """``data`` with our header, answering the host first (as x3270 does)."""
        self.ack()
        header = bytes([dtype, 0, 0]) + self.seq.to_bytes(2, "big")
        if F_RESPONSES in self.functions:
            self.seq = (self.seq + 1) & 0x7FFF
        return header + data
