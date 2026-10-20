import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_app_icon_and_logo(app):
    from cherminal.gui.icons import SIZES, app_icon, logo
    icon = app_icon()
    assert not icon.isNull()
    assert {s.width() for s in icon.availableSizes()} == set(SIZES)
    for dark in (True, False):
        pix = logo(dark, 300)
        assert pix.width() == 300 and pix.height() > 50

