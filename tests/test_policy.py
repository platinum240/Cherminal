import os
import ssl
import sys

import pytest

from cherminal import __main__ as cli
from cherminal import policy
from cherminal.config import ProfileStore, SessionProfile
from cherminal.policy import Policy, PolicyError
from cherminal.session import Session
from cherminal.transport import from_profile


def write(path, text):
    path.write_text(text)
    return path


def test_no_file_means_no_restrictions(tmp_path):
    rules = policy.load(tmp_path / "missing.toml")
    assert rules == Policy() and not rules.active
    rules.check(SessionProfile(transport="local"))


def test_reads_every_setting(tmp_path):
    rules = policy.read(write(tmp_path / "p.toml", """
limited = true
allowed_transports = ["telnet", "ssh"]
file_upload = false
print_to_file = false
require_tls = true
require_tls_verify = true
tls_ca_file = "/etc/cherminal/ca.pem"
"""))
    assert rules.limited and not rules.file_upload and not rules.print_to_file
    assert rules.allowed_transports == ("telnet", "ssh")
    assert rules.require_tls and rules.require_tls_verify
    assert rules.tls_ca_file == "/etc/cherminal/ca.pem"
    assert rules.source.endswith("p.toml") and rules.active


@pytest.mark.parametrize("text, message", [
    ("limted = true", "unknown policy setting"),
    ("limited = 1", "true or false"),
    ('allowed_transports = ["rdp"]', "unknown transport"),
    ('allowed_transports = "ssh"', "must be a list"),
    ("limited = ", "policy.toml"),            # not valid TOML
])
def test_mistakes_are_errors(tmp_path, text, message):
    with pytest.raises(PolicyError, match=message):
        policy.read(write(tmp_path / "policy.toml", text))


def test_check_transports_and_tls():
    rules = Policy(allowed_transports=("telnet",), require_tls=True, require_tls_verify=True)
    with pytest.raises(PolicyError, match="ssh connections are not allowed"):
        rules.check(SessionProfile(transport="ssh", host="h"))
    with pytest.raises(PolicyError, match="only allows Telnet over TLS"):
        rules.check(SessionProfile(transport="telnet", host="h"))
    with pytest.raises(PolicyError, match="certificate"):
        rules.check(SessionProfile(transport="telnet", host="h", tls=True, tls_verify=False))
    rules.check(SessionProfile(transport="telnet", host="h", tls=True))


def test_tls_settings_are_optional():
    # By default the policy enforces nothing about TLS.
    Policy().check(SessionProfile(transport="telnet", host="h"))
    Policy().check(SessionProfile(transport="telnet", host="h", tls=True, tls_verify=False))


def test_limited_policy_refuses_local_shell():
    assert not Policy(limited=True).local_shell
    with pytest.raises(PolicyError, match="local shell"):
        Policy(limited=True).check(SessionProfile(transport="local"))


def test_session_refuses_what_policy_forbids(tmp_path):
    policy.set_current(Policy(allowed_transports=("ssh",)))
    with pytest.raises(ValueError, match="telnet connections are not allowed"):
        Session(SessionProfile(transport="telnet", host="h"), ProfileStore(tmp_path, site_roots=[]))


def test_ca_file_reaches_telnet(tmp_path):
    policy.set_current(Policy(tls_ca_file="/etc/cherminal/ca.pem"))
    t = from_profile(SessionProfile(transport="telnet", host="h", tls=True))
    assert t.ca_file == "/etc/cherminal/ca.pem"


def test_bad_ca_file_fails_before_connecting(monkeypatch):
    from cherminal.transport.telnet import TelnetTransport
    import socket
    monkeypatch.setattr(socket, "create_connection",
                        lambda *a, **k: pytest.fail("connected before loading the CA"))
    t = TelnetTransport("h", 992, tls=True, ca_file="/nonexistent/ca.pem")
    with pytest.raises((OSError, ssl.SSLError)):
        t._open()


# ------------------------------------------------------------------ CLI

@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_DIRS", str(tmp_path / "none"))
    monkeypatch.delenv("CHERMINAL_SITE_DIR", raising=False)
    monkeypatch.delenv("APPIMAGE", raising=False)
    seen = {}
    pytest.importorskip("PyQt6.QtWidgets")
    import cherminal.gui.app as gui_app
    monkeypatch.setattr(gui_app, "run", lambda profiles, store, show_manager, limited=False:
                        seen.update(names=[p.name for p in profiles], limited=limited) or 0)
    return seen


def test_policy_turns_on_limited(cli_env, tmp_path):
    write(policy.POLICY_PATH, "limited = true\n")
    ProfileStore().save(SessionProfile(name="Mainframe A", transport="telnet", host="mf"))
    assert cli.main(["Mainframe A"]) == 0
    assert cli_env == {"names": ["Mainframe A"], "limited": True}


def test_broken_policy_stops_start(cli_env, capsys):
    write(policy.POLICY_PATH, "limited = maybe\n")
    assert cli.main([]) == 2
    assert "not starting" in capsys.readouterr().err
    assert cli_env == {}


def test_cli_refuses_forbidden_ad_hoc(cli_env, capsys):
    write(policy.POLICY_PATH, 'allowed_transports = ["telnet"]\n')
    assert cli.main(["--local"]) == 2
    assert "local connections are not allowed" in capsys.readouterr().err


def test_check_policy(tmp_path, capsys):
    good = write(tmp_path / "good.toml", "print_to_file = false\n")
    assert cli.main(["--check-policy", str(good)]) == 0
    assert "print_to_file = False" in capsys.readouterr().out
    bad = write(tmp_path / "bad.toml", "print_to_fiel = false\n")
    assert cli.main(["--check-policy", str(bad)]) == 2
    assert "unknown policy setting" in capsys.readouterr().err


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0,
                    reason="root can read any file; Windows has no chmod 0")
def test_unreadable_policy_is_an_error(tmp_path):
    path = write(tmp_path / "policy.toml", "limited = true\n")
    path.chmod(0)
    with pytest.raises(PolicyError, match="cannot read"):
        policy.load(path)
