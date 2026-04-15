from pathlib import Path
from unittest.mock import patch

from jhack.config import get_home_dir


@patch("jhack.config.getpass.getuser", return_value="john.doe@example.com")
def test_get_home_dir_email_username(mock_getuser):
    """expanduser() raises RuntimeError for usernames with special characters like '@'."""
    result = get_home_dir()
    assert result == Path("/home/john.doe@example.com")
