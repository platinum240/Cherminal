def test_cursor_address_and_clear(term):
    emu, s, _ = term("wyse60")
    emu.feed(b"\x1b= %X")          # row 0, col 5
    assert s.lines[0][5].char == "X"
    emu.feed(b"\x1b*")
    assert s.text() == "" and (s.y, s.x) == (0, 0)


def test_extended_address(term):
    emu, s, _ = term("wyse60")
    emu.feed(b"\x1ba10R20CQ")
    assert s.lines[9][19].char == "Q"


def test_control_motion(term):
    emu, s, _ = term("wyse50")
    emu.feed(b"ab\x08\x08\x0c\x0aZ\x0bY\x1e")
    assert s.line_text(0) == "abY"
    assert s.line_text(1) == " Z"
    assert (s.y, s.x) == (0, 0)


def test_line_edit(term):
    emu, s, _ = term("wyse60", cols=10, rows=4)
    emu.feed(b"one\r\ntwo\r\nthree")
    emu.feed(b"\x1b=!\x20\x1bE")    # row 1 -> insert line
    assert s.text() == "one\n\ntwo\nthree"
    emu.feed(b"\x1bR")
    assert s.text() == "one\ntwo\nthree"
    emu.feed(b"\x1b=!\x20\x1bW")
    assert s.line_text(1) == "wo"
    emu.feed(b"\x1bT")
    assert s.line_text(1) == ""


def test_attributes(term):
    emu, s, _ = term("wyse60")
    emu.feed(b"\x1bG4R\x1bG8U\x1bG0N")
    assert s.lines[0][0].attr.reverse
    assert s.lines[0][1].attr.underline and not s.lines[0][1].attr.reverse
    assert s.lines[0][2].attr.reverse is False


def test_ignored_strings_are_consumed(term):
    emu, s, _ = term("wyse60")
    emu.feed(b"\x1bFstatus text\r\x1bz@hello\x7fOK")
    assert s.line_text(0) == "OK"


def test_split_sequence(term):
    emu, s, _ = term("wyse60")
    emu.feed(b"\x1b")
    emu.feed(b"=")
    emu.feed(b"\"")
    emu.feed(b"#X")
    assert s.lines[2][3].char == "X"
