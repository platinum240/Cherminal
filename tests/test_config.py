import pytest

from cherminal.config import ProfileStore, SessionProfile


def test_save_load_roundtrip(tmp_path):
    store = ProfileStore(tmp_path)
    p = SessionProfile(name="Warehouse Box", transport="telnet", host="10.0.0.5",
                       emulation="wyse60", keys={"F12": "^AK\\r"}, macros={"login": "op\\r"})
    path = store.save(p)
    assert path.name == "warehouse-box.toml"
    assert "font_size" not in path.read_text()     # defaults are not written
    loaded = store.load("Warehouse Box")
    assert loaded == p
    assert loaded.effective_port == 23
    assert [x.name for x in store.list()] == ["Warehouse Box"]


def test_rename_removes_old_file(tmp_path):
    store = ProfileStore(tmp_path)
    p = SessionProfile(name="old")
    store.save(p)
    p.name = "new"
    store.save(p, old_name="old")
    assert [x.name for x in store.list()] == ["new"]


def test_validation():
    with pytest.raises(ValueError):
        SessionProfile(emulation="vt999")
    with pytest.raises(ValueError):
        SessionProfile.from_dict({"name": "x", "bogus": 1})


def test_broken_file_does_not_hide_others(tmp_path):
    store = ProfileStore(tmp_path)
    store.save(SessionProfile(name="good"))
    (store.sessions_dir / "bad.toml").write_text("this is = = not toml")
    assert [x.name for x in store.list()] == ["good"]


def test_keymap_layering(tmp_path):
    store = ProfileStore(tmp_path)
    store.save_keymap("site", {"F1": "\\e[11~", "F2": "hello"}, inherit="vt220")
    p = SessionProfile(emulation="vt220", keymap="site", backspace="bs",
                       enter_sends="crlf", keys={"F2": "override"})
    km = store.build_keymap(p)
    assert km.lookup("F1").value == "\x1b[11~"       # keymap file
    assert km.lookup("F2").value == "override"       # session [keys] wins
    assert km.lookup("Backspace").value == "\b"      # backspace setting
    assert km.lookup("Enter").value == "\r\n"
    assert km.lookup("F6").value == "\x1b[17~"       # inherited built-in


def test_keymap_inherit_loop(tmp_path):
    store = ProfileStore(tmp_path)
    store.keymaps_dir.mkdir(parents=True)
    (store.keymaps_dir / "a.toml").write_text('inherit = "b"\n')
    (store.keymaps_dir / "b.toml").write_text('inherit = "a"\n')
    with pytest.raises(ValueError):
        store.load_keymap_layers("a")


def test_builtin_keymap_name_protected(tmp_path):
    with pytest.raises(ValueError):
        ProfileStore(tmp_path).save_keymap("vt220", {}, inherit="vt100")
