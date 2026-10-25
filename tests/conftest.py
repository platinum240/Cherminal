import pytest

from cherminal import emulation
from cherminal.screen import Screen


@pytest.fixture
def term():
    """Factory: term("vt220") -> (emulation, screen, replies)."""
    def make(name="vt220", cols=80, rows=24, **kw):
        screen = Screen(cols, rows)
        replies = []
        emu = emulation.create(name, screen, replies.append, **kw)
        return emu, screen, replies
    return make


@pytest.fixture(autouse=True)
def no_site_policy(monkeypatch, tmp_path_factory):
    """Tests never pick up the machine's policy file or managed preferences."""
    from cherminal import policy
    monkeypatch.setattr(policy, "POLICY_PATH", tmp_path_factory.mktemp("policy") / "policy.toml")
    monkeypatch.setattr(policy, "managed_prefs_paths", lambda: [])
    yield
    policy.set_current(policy.Policy())
