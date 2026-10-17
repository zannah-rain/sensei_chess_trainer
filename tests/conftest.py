import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    """A single QApplication for the whole test session - constructing any QWidget requires one to exist."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
