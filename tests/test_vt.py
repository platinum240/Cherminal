from cherminal.screen import Attr


def test_text_and_newlines(term):
    emu, s, _ = term()
    emu.feed(b"hello\r\nworld")
    assert s.text() == "hello\nworld"
    assert (s.y, s.x) == (1, 5)


def test_cursor_position_and_erase(term):
    emu, s, _ = term()
    emu.feed(b"abcdef\x1b[1;3H\x1b[K")
    assert s.line_text(0) == "ab"
    emu.feed(b"\x1b[2J\x1b[5;10HX")
    assert s.lines[4][9].char == "X"
    assert s.line_text(0) == ""


def test_autowrap_defers_until_next_char(term):
    emu, s, _ = term(cols=5, rows=3)
    emu.feed(b"abcde")
    assert (s.y, s.x) == (0, 4)
    emu.feed(b"f")
    assert s.text() == "abcde\nf"


def test_scroll_region_and_scrollback(term):
    emu, s, _ = term(cols=10, rows=4)
    emu.feed(b"1\r\n2\r\n3\r\n4\r\n5")
    assert s.text() == "2\n3\n4\n5"
    assert "".join(c.char for c in s.scrollback[0]).strip() == "1"
    emu.feed(b"\x1b[2;3r\x1b[3;1H\n")
    assert s.text() == "2\n4\n\n5"


def test_insert_delete(term):
    emu, s, _ = term()
    emu.feed(b"abcdef\x1b[1;2H\x1b[2P")
    assert s.line_text(0) == "adef"
    emu.feed(b"\x1b[2@")
    assert s.line_text(0) == "a  def"


def test_sgr(term):
    emu, s, _ = term()
    emu.feed(b"\x1b[1;4;31;44mX\x1b[0mY\x1b[38;5;200mZ\x1b[38;2;1;2;3mW")
    assert s.lines[0][0].attr == Attr(fg=1, bg=4, bold=True, underline=True)
    assert s.lines[0][1].attr == Attr()
    assert s.lines[0][2].attr.fg == 200
    assert s.lines[0][3].attr.fg == (1, 2, 3)


def test_dec_line_drawing(term):
    emu, s, _ = term()
    emu.feed(b"\x1b(0lqk\x1b(Bq")
    assert s.line_text(0) == "┌─┐q"


def test_replies(term):
    emu, s, replies = term("vt220")
    emu.feed(b"\x1b[c\x1b[3;7H\x1b[6n")
    assert replies == [b"\x1b[?62;1;2;6;7;8;9c", b"\x1b[3;7R"]


def test_vt100_da(term):
    emu, _, replies = term("vt100")
    emu.feed(b"\x1b[c")
    assert replies == [b"\x1b[?1;2c"]


def test_modes_for_keymap(term):
    emu, s, _ = term()
    emu.feed(b"\x1b[?1h\x1b=")
    assert emu.app_cursor and emu.app_keypad
    emu.feed(b"\x1b[?1l\x1b>")
    assert not emu.app_cursor and not emu.app_keypad


def test_alt_screen(term):
    emu, s, _ = term()
    emu.feed(b"main\x1b[?1049h")
    assert s.text() == ""
    emu.feed(b"alt\x1b[?1049l")
    assert s.text() == "main"


def test_osc_title_and_split_sequences(term):
    emu, s, _ = term()
    for chunk in (b"\x1b]0;my ti", b"tle\x07\x1b[", b"2", b"J"):
        emu.feed(chunk)
    assert s.title == "my title"


def test_c1_controls_in_8bit_mode(term):
    emu, s, _ = term("vt220", encoding="latin-1")
    emu.feed(b"abc\x9b2;2HX")
    assert s.lines[1][1].char == "X"


def test_utf8_split_across_reads(term):
    emu, s, _ = term("xterm")
    data = "héllo".encode()
    emu.feed(data[:2])
    emu.feed(data[2:])
    assert s.line_text(0) == "héllo"


def test_sco_colours_and_cp437(term):
    emu, s, _ = term("ansi")
    emu.feed(b"\x1b[=1FA\xc4")
    assert s.lines[0][0].attr.fg == 4   # PC blue -> ANSI blue
    assert s.lines[0][1].char == "─"


def test_answerback(term):
    emu, _, replies = term(answerback="CHERM1")
    emu.feed(b"\x05")
    assert replies == [b"CHERM1"]


def test_resize_keeps_cursor_row(term):
    emu, s, _ = term(cols=10, rows=5)
    emu.feed(b"1\r\n2\r\n3\r\n4\r\n5")
    s.resize(12, 3)
    assert s.text() == "3\n4\n5"
    assert s.y == 2
