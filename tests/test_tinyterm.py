import pytest

from cherminal import __main__ as cli
from cherminal import desktop, system, tinyterm
from cherminal.config import ProfileStore

# The parts of a real TinyTERM file that matter, with made-up hosts. Real
# files have several hundred more keys, CRLF line ends and sections in
# either [TERM.emu] or [term.emu] case.
SAMPLE = """[TERM.emu]
emulate=13
colorfg0=15
colorbg0=2
cursor=0
col=132
wru=
scrollback=999
user=
password=
login=0
loginscheme=UNIX Password
cptrxin=STD 437 MS-DOS Latin US
lines=24
bsdel=0
stpsvrW1=$
rtscts=0

[TERM.comm]
node=host1.example.com|ss://host2.example.com|host3.example.com|
port=23
cdelay=TELNET
commtype=5
baud=19200
ComPort=1

[TERM.gen]
xwindow=-4
"""


def write(tmp_path, text, name="Store 12.tpx"):
    path = tmp_path / name
    path.write_bytes(text.replace("\n", "\r\n").encode("cp1252"))
    return path


def test_reads_a_telnet_session(tmp_path):
    profile, notes = tinyterm.read(write(tmp_path, SAMPLE))
    assert profile.name == "Store 12"
    assert (profile.transport, profile.host, profile.port) == ("telnet", "host1.example.com", 0)
    assert profile.emulation == "tvi950"
    assert (profile.cols, profile.rows, profile.scrollback) == (132, 24, 999)
    assert (profile.fg_color, profile.bg_color) == ("#ffff55", "#0000aa")   # yellow on blue
    assert profile.encoding == "cp437"
    assert profile.backspace == "bs" and profile.enter_sends == "cr"
    assert profile.ask_login
    assert notes == ["TinyTERM also lists host2.example.com, host3.example.com"]


def test_parse_keeps_values_exactly():
    assert tinyterm.parse("[TERM.emu]\r\nstpsvrW1=$  \r\n").get("term.emu", "stpsvrW1") == "$  "
    tpx = tinyterm.parse(SAMPLE)
    assert tpx.get("term.comm", "COMMTYPE") == "5"


@pytest.mark.parametrize("code, emulation", [(3, "vt220"), (5, "vt100"), (9, "scoansi"),
                                             (10, "wyse60"), (14, "wyse50"), (15, "tvi925")])
def test_emulation_codes(tmp_path, code, emulation):
    profile, _ = tinyterm.read(write(tmp_path, SAMPLE.replace("emulate=13", f"emulate={code}")))
    assert profile.emulation == emulation


def test_unknown_emulation_falls_back_with_a_note(tmp_path):
    profile, notes = tinyterm.read(write(tmp_path, SAMPLE.replace("emulate=13", "emulate=12")))
    assert profile.emulation == "scoansi"
    assert any("PC Term" in n for n in notes)


def test_mainframe_session(tmp_path):
    profile, _ = tinyterm.read(write(tmp_path, SAMPLE.replace("emulate=13", "emulate=24")))
    assert profile.emulation == "ibm3278-3" and profile.transport == "telnet"
    assert profile.cols == 80 and not profile.fg_color and not profile.encoding


def test_serial_session(tmp_path, monkeypatch):
    monkeypatch.setattr(system, "IS_WINDOWS", False)
    monkeypatch.setattr(system, "IS_MAC", False)
    text = SAMPLE.replace("commtype=5", "commtype=0").replace(
        "node=host1.example.com|ss://host2.example.com|host3.example.com|", "node=").replace(
        "ComPort=1", "ComPort=2\nparity=2\nstopbits=2").replace("rtscts=0", "rtscts=1")
    profile, notes = tinyterm.read(write(tmp_path, text))
    assert profile.transport == "serial" and profile.serial_device == "/dev/ttyS1"
    assert (profile.baud, profile.parity, profile.stop_bits, profile.flow_control) == \
        (19200, "even", 2, "rtscts")
    assert any("COM2" in n for n in notes)


def test_user_name_and_password(tmp_path):
    text = SAMPLE.replace("user=\n", "user=clerk\n").replace("password=\n", "password=s3cr3t\n")
    profile, notes = tinyterm.read(write(tmp_path, text))
    assert profile.username == "clerk"
    assert any("password" in n for n in notes)
    assert "s3cr3t" not in str(profile.to_dict())


def test_not_a_tinyterm_file(tmp_path):
    with pytest.raises(ValueError):
        tinyterm.read(write(tmp_path, "[other]\na=1\n"))


def test_cli_import_and_open(tmp_path, monkeypatch, capsys):
    store = ProfileStore(tmp_path / "config")
    monkeypatch.setattr(cli, "ProfileStore", lambda: store)
    path = write(tmp_path, SAMPLE)
    assert cli.main(["--import", str(path)]) == 0
    out = capsys.readouterr().out
    assert "imported Store 12" in out and "host2.example.com" in out
    assert store.load("Store 12").host == "host1.example.com"

    class Args:
        sessions, ssh, telnet, serial, local, emulation = [str(path)], None, None, None, False, None
    opened = cli.build_profiles(Args, ProfileStore(tmp_path / "other"))
    assert [p.host for p in opened] == ["host1.example.com"]


def test_desktop_entry_declares_tpx(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    entry = desktop.install()
    assert f"MimeType={desktop.TPX_MIME};" in entry.read_text()
    assert 'pattern="*.tpx"' in (tmp_path / "mime/packages/cherminal.xml").read_text()
