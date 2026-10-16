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
