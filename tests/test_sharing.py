import tomllib
from pathlib import Path

import pytest

from cherminal import __main__ as cli
from cherminal.config import ProfileStore, SessionProfile, site_dirs


def mainframe(name="Mainframe A", **kw):
    return SessionProfile(name=name, transport="telnet", host="10.1.1.10", emulation="vt220",
                          keymap="mainframe", keys={"F13": "\\e[25~"},
                          macros={"logon": "user\\r"}, **kw)


def test_bundle_carries_session_and_its_keymap_chain(tmp_path):
    src = ProfileStore(tmp_path / "admin")
    src.save_keymap("site-base", {"F1": "\\e[11~"}, inherit="vt220")
    src.save_keymap("mainframe", {"F3": "\\eOR", "F2": "pf2"}, inherit="site-base")
    src.save(mainframe())
    src.save(mainframe("Mainframe B", port=2023))
    bundle = src.export_bundle(["Mainframe A", "Mainframe B"], tmp_path / "site.cherminal")
    data = tomllib.loads(bundle.read_text())
    assert set(data["keymap"]) == {"mainframe", "site-base"}   # vt220 is built in

    client = ProfileStore(tmp_path / "client")
    assert client.import_bundle(bundle) == ["Mainframe A", "Mainframe B"]
    assert client.load("Mainframe A") == src.load("Mainframe A")
    km_src, km_client = (s.build_keymap(s.load("Mainframe B")) for s in (src, client))
    for key in ("F1", "F2", "F13", "F6"):
        assert km_client.lookup(key) == km_src.lookup(key)
    assert km_client.lookup("F1").value == "\x1b[11~"


def test_import_replaces_same_named(tmp_path):
    store = ProfileStore(tmp_path / "c")
    store.save(SessionProfile(name="Mainframe A", host="old"))
    other = ProfileStore(tmp_path / "a")
    other.save_keymap("mainframe", {}, inherit="vt220")
    other.save(mainframe())
    store.import_bundle(other.export_bundle(["Mainframe A"], tmp_path / "x.cherminal"))
    assert store.load("Mainframe A").host == "10.1.1.10"


def test_bundle_rejects_unsafe_or_builtin_keymap_names(tmp_path):
    store = ProfileStore(tmp_path / "c")
    bad = tmp_path / "bad.cherminal"
    bad.write_text('cherminal_bundle = 1\n[keymap."../evil"]\ninherit = "vt220"\n')
    with pytest.raises(ValueError):
        store.import_bundle(bad)
    bad.write_text('cherminal_bundle = 1\n[keymap.vt220]\ninherit = "vt100"\n')
    with pytest.raises(ValueError):
        store.import_bundle(bad)
    assert not (tmp_path / "c" / "keymaps").exists()


def test_site_folder_sessions_and_user_overrides(tmp_path):
    admin = ProfileStore(tmp_path / "admin")
    admin.save_keymap("mainframe", {"F2": "pf2"}, inherit="vt220")
    admin.save(mainframe())
    site = tmp_path / "site"
    site.mkdir()
    admin.export_bundle(["Mainframe A"], site / "mainframes.cherminal")
    (site / "sessions").mkdir()
    (site / "sessions" / "other.toml").write_text('name = "Other"\nhost = "h"\n')

    store = ProfileStore(tmp_path / "user", site_roots=[site])
    assert [p.name for p in store.list()] == ["Mainframe A", "Other"]
    assert store.origin("Mainframe A") == "shared"
    assert store.build_keymap(store.load("Mainframe A")).lookup("F2").value == "pf2"
    assert "mainframe" in store.keymap_names()

    edited = store.load("Mainframe A")
    edited.host = "mine"
    store.save(edited)
    assert store.origin("Mainframe A") == "customised"
    assert store.load("Mainframe A").host == "mine"
    store.delete("Mainframe A")                     # back to the shared copy
    assert store.load("Mainframe A").host == "10.1.1.10"
    assert not (tmp_path / "user" / "keymaps").exists()   # nothing copied to the user


def test_earlier_site_folder_wins(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for root, host in ((a, "first"), (b, "second")):
        (root / "sessions").mkdir(parents=True)
        (root / "sessions" / "s.toml").write_text(f'name = "S"\nhost = "{host}"\n')
    assert ProfileStore(tmp_path / "u", site_roots=[a, b]).load("S").host == "first"


def test_site_dirs_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("CHERMINAL_SITE_DIR", f"{tmp_path}/share:{tmp_path}/usb")
    monkeypatch.setenv("APPIMAGE", f"{tmp_path}/apps/Cherminal.AppImage")
    monkeypatch.setenv("XDG_CONFIG_DIRS", "/etc/xdg")
    assert site_dirs() == [tmp_path / "share", tmp_path / "usb",
                           tmp_path / "apps" / "cherminal-config",
                           Path("/etc/xdg/cherminal")]


def test_cli_export_and_import(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "one"))
    monkeypatch.setenv("XDG_CONFIG_DIRS", str(tmp_path / "none"))
    monkeypatch.delenv("CHERMINAL_SITE_DIR", raising=False)
    monkeypatch.delenv("APPIMAGE", raising=False)
    store = ProfileStore()
    store.save_keymap("mainframe", {"F2": "pf2"}, inherit="vt220")
    store.save(mainframe())
    out = tmp_path / "site.cherminal"
    assert cli.main(["--export", str(out)]) == 0
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "two"))
    assert cli.main(["--import", str(out)]) == 0
    assert "Mainframe A" in capsys.readouterr().out
    assert ProfileStore().load("Mainframe A").keymap == "mainframe"
    assert cli.main(["--import", str(tmp_path / "missing.cherminal")]) == 2
