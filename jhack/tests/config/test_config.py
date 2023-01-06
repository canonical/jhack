import tempfile
from pathlib import Path
from textwrap import dedent

from jhack.conf.conf import Config


def test_config():
    data = dedent(
        """
    [test]
    foo = true
    bar = "baz"
    """
    )

    with tempfile.NamedTemporaryFile() as tf:
        path = Path(tf.name)
        path.write_text(data)

        cfg = Config(path)

        assert cfg._data is None
        cfg.data  # noqa
        assert cfg._data

    assert cfg["test"]["foo"] is True
    assert cfg["test"]["bar"] == "baz"


def test_default():
    cfg = Config()
    assert isinstance(cfg["nuke"]["ask_for_confirmation"], bool)
