"""Serial ports via pyserial."""

from __future__ import annotations

from .base import Transport

PARITY = {"none": "N", "even": "E", "odd": "O", "mark": "M", "space": "S"}


class SerialTransport(Transport):
    def __init__(self, device: str, baud: int = 9600, data_bits: int = 8,
                 parity: str = "none", stop_bits: float = 1, flow_control: str = "none"):
        super().__init__()
        self.device = device
        self.settings = dict(baudrate=baud, bytesize=data_bits, parity=PARITY[parity],
                             stopbits=stop_bits, xonxoff=flow_control == "xonxoff",
                             rtscts=flow_control == "rtscts")
        self.port = None

    def _open(self) -> None:
        import serial
        self.port = serial.Serial(self.device, timeout=0.2, **self.settings)

    def _read(self) -> bytes:
        while not self._closing:
            n = max(1, self.port.in_waiting)
            data = self.port.read(n)
            if data:
                return data
        return b""

    def _write(self, data: bytes) -> None:
        self.port.write(data)

    def send_break(self) -> None:
        if self.port:
            self.port.send_break(0.25)

    def _close(self) -> None:
        if self.port:
            self.port.close()
