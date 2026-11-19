from cherminal.transport.telnet import (
    BINARY, DO, DONT, ECHO, IAC, NAWS, SB, SE, SGA, TTYPE, WILL, WONT, TelnetProtocol)


def make():
    sent = []
    proto = TelnetProtocol(sent.append, term_type="WY60", cols=132, rows=24)
    return proto, sent


def test_start_offers_options():
    proto, sent = make()
    proto.start()
    assert bytes([IAC, WILL, TTYPE]) in sent and bytes([IAC, DO, ECHO]) in sent


def test_ack_of_our_offer_is_not_echoed_back():
    proto, sent = make()
    proto.start()
    sent.clear()
    proto.receive(bytes([IAC, DO, TTYPE, IAC, WILL, ECHO]))
    assert sent == []
    assert TTYPE in proto.local and proto.server_echoes


def test_naws_and_ttype():
    proto, sent = make()
    proto.receive(bytes([IAC, DO, NAWS]))
    assert sent[0] == bytes([IAC, WILL, NAWS])
    assert sent[1] == bytes([IAC, SB, NAWS, 0, 132, 0, 24, IAC, SE])
    sent.clear()
    proto.receive(bytes([IAC, SB, TTYPE, 1, IAC, SE]))
    assert sent == [bytes([IAC, SB, TTYPE, 0]) + b"WY60" + bytes([IAC, SE])]


def test_refuses_unknown_options():
    proto, sent = make()
    proto.receive(bytes([IAC, DO, 39, IAC, WILL, 39]))
    assert sent == [bytes([IAC, WONT, 39]), bytes([IAC, DONT, 39])]


def test_data_filtering():
    proto, _ = make()
    out = proto.receive(b"ab" + bytes([IAC, IAC]) + b"c\r\x00d" + bytes([IAC, 241]) + b"e")
    assert out == b"ab\xffc\rde"


def test_split_command_across_reads():
    proto, sent = make()
    assert proto.receive(bytes([IAC])) == b""
    assert proto.receive(bytes([WILL])) == b""
    proto.receive(bytes([SGA]) + b"x")
    assert sent == [bytes([IAC, DO, SGA])]


def test_encode():
    proto, _ = make()
    assert proto.encode(b"a\xffb\r") == b"a\xff\xffb\r\x00"
    assert proto.encode(b"x\r\n") == b"x\r\n"
    proto.receive(bytes([IAC, DO, BINARY]))
    assert proto.encode(b"\r") == b"\r"


def test_trace_records_the_conversation(tmp_path, monkeypatch):
    import socket
    import threading

    from cherminal.transport import telnet
    trace = tmp_path / "trace.txt"
    monkeypatch.setenv(telnet.TRACE_ENV, str(trace))
    srv = socket.create_server(("127.0.0.1", 0))

    def serve():
        conn, _ = srv.accept()
        conn.sendall(b"login: ")
        while conn.recv(100):
            pass
        conn.close()
    threading.Thread(target=serve, daemon=True).start()
    t = telnet.TelnetTransport("127.0.0.1", srv.getsockname()[1], term_type="tvi950")
    t._open()
    assert t._read() == b"login: "
    t._close()
    srv.close()
    text = trace.read_text()
    assert "connected to" in text and "> b'\\xff\\xfb\\x18" in text and "< b'login: '" in text


def test_login_answers_the_prompts(monkeypatch):
    import socket
    import threading

    from cherminal.transport import telnet
    monkeypatch.delenv(telnet.TRACE_ENV, raising=False)
    srv = socket.create_server(("127.0.0.1", 0))
    got = []

    def serve():
        conn, _ = srv.accept()
        conn.settimeout(5)
        # Ask for the environment; expect the user name the person typed.
        conn.sendall(bytes([telnet.IAC, telnet.DO, telnet.NEW_ENVIRON]))
        buf = b""
        while b"\r" not in buf.replace(b"\r\x00", b"", 1) and b"\r\x00" not in buf:
            buf += conn.recv(100)
        conn.sendall(bytes([telnet.IAC, telnet.SB, telnet.NEW_ENVIRON, telnet.ENV_SEND,
                            telnet.IAC, telnet.SE]))
        conn.sendall(b"\r\nlogin: ")
        buf = b""
        while b"clerk\r" not in buf:
            buf += conn.recv(100)
        got.append(buf)
        conn.sendall(b"Password:")
        buf = b""
        while b"s3cr3t\r" not in buf:
            buf += conn.recv(100)
        got.append(buf)
        conn.sendall(b"\r\n$ ")
        while conn.recv(100):
            pass
        conn.close()
    threading.Thread(target=serve, daemon=True).start()
    asked = []

    def ask(host, user, error):
        asked.append((host, user))
        return "clerk", "s3cr3t"
    t = telnet.TelnetTransport("127.0.0.1", srv.getsockname()[1], term_type="tvi950",
                               username="old", ask_login=ask)
    t._open()
    out = b""
    while b"$ " not in out:
        out += t._read()
    t._close()
    srv.close()
    assert asked == [("127.0.0.1", "old")]
    env = bytes([telnet.ENV_VAR]) + b"USER" + bytes([telnet.ENV_VALUE]) + b"clerk"
    assert env in got[0] and b"s3cr3t" not in got[0]
    assert b"s3cr3t\r" in got[1]


def test_login_cancelled():
    from cherminal.transport import telnet
    t = telnet.TelnetTransport("127.0.0.1", 1, ask_login=lambda h, u, e: None)
    import pytest
    with pytest.raises(OSError, match="cancelled"):
        t._open()
