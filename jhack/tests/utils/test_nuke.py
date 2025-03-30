import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from jhack.utils.nuke import Nukeable, app


class TestModelNuking(unittest.TestCase):

    @patch("jhack.utils.nuke.fire")
    def test_nuke_model(self, mock_fire):
        test_model = "testing"

        runner = CliRunner()
        _ = runner.invoke(app, ["--model", test_model])

        expected_nukeable = Nukeable(name=test_model, type="model")

        mock_fire.assert_called_once_with(
            expected_nukeable,
            f"juju destroy-model --force --no-wait --destroy-storage --no-prompt {test_model}",
        )


if __name__ == "__main__":
    unittest.main()
