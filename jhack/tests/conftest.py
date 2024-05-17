import os

import pytest


@pytest.fixture(autouse=True)
def enable_devmode():
    os.environ["JHACK_PROFILE"] = "devmode"
