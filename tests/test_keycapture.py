import socket
import threading

from cherminal.tools.keycapture import DO, IAC, SB, SE, TTYPE, WILL, run


def test_capture_session():
    server, client = socket.socketpair()
    result = {}

    def serve():
        result["out"] = run(server, ["F1", "Up", "F2", "F3"])

    t = threading.Thread(target=serve)
    t.start()
    # The client answers TTYPE, then presses F1, Up, skips F2, finishes at F3.
    client.sendall(bytes([IAC, WILL, TTYPE, IAC, SB, TTYPE, 0]) + b"WY60" + bytes([IAC, SE]))
    for key in (b"\x01@\r\x00", b"\x0b", b" ", b"\x1d"):
        threading.Event().wait(1.0)
        client.sendall(key)
    t.join(timeout=10)
    client.close()
    captured, term_type = result["out"]
    assert term_type == "WY60"
    assert captured == {"F1": "^A@\\r", "Up": "^K"}
