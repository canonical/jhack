import contextlib
from contextlib import ExitStack
from functools import partial
from pathlib import Path
import json as json_
from unittest.mock import patch

MOCKS_PATH = Path(__file__).parent / "mocks"


def fake_juju_status(model=None, json: bool = False, case: str = "noop"):
    ext = ".json" if json else ".txt"
    model_identifier = model.replace(":", "_").replace("/", "_") if model else model
    source = MOCKS_PATH / case / (f"full_status_{model_identifier}" + ext)
    raw = source.read_text()
    if json:
        return json_.loads(raw)
    return raw


def fake_juju_show_unit(unit_name, model=None, *args, case: str = "noop", **kwargs):
    model_identifier = model.replace(":", "_").replace("/", "_") if model else model
    source = MOCKS_PATH / case / f"{unit_name.replace('/', '')}_{model_identifier}_show.json"
    if not source.exists():
        raise ValueError(f"mock source not found for {unit_name}: {source}")
    return json_.loads(source.read_text())


@contextlib.contextmanager
def load_mocks(name):
    with ExitStack() as es:
        es.enter_context(
            patch(
                "jhack.utils.show_relation._juju_status",
                wraps=partial(fake_juju_status, case=name),
            )
        )
        es.enter_context(
            patch(
                "jhack.utils.show_relation._show_unit",
                wraps=partial(fake_juju_show_unit, case=name),
            )
        )

        yield
