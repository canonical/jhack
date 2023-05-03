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

    assert cfg.get("test", "foo") is True
    assert cfg.get("test", "bar") == "baz"


def test_defaults():
    defaults = dedent(
        """
    [test]
    foo = true
    bar = "baz"
    """
    )

    data = dedent(
        """
    [test]
    foo = false
    """
    )
    with tempfile.NamedTemporaryFile() as dftf:
        defaults_path = Path(dftf.name)
        defaults_path.write_text(defaults)
        old_def = Config._DEFAULTS
        Config._DEFAULTS = defaults_path

        with tempfile.NamedTemporaryFile() as tf:
            path = Path(tf.name)
            path.write_text(data)

            cfg = Config(path)

            assert cfg._data is None
            cfg.data  # noqa
            assert cfg._data

        assert cfg.get("test", "foo") is False
        assert cfg.get("test", "bar") == "baz"

    Config._DEFAULTS = old_def
