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
