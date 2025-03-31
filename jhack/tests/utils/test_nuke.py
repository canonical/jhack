from unittest.mock import patch

from typer import Typer
from typer.testing import CliRunner

from jhack.utils.nuke import Nukeable, nuke


def test_nuke_model():
    test_model = "testing"

    runner = CliRunner()
    app = Typer()
    app.command()(nuke)
    with patch("jhack.utils.nuke.fire") as mock_fire:
        _ = runner.invoke(app, ["--model", test_model])

        expected_nukeable = Nukeable(name=test_model, type="model")
        mock_fire.assert_called_once_with(
            expected_nukeable,
            f"juju destroy-model --force --no-wait --destroy-storage --no-prompt {test_model}",
        )
