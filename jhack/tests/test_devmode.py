import io
import os

import pytest

from jhack.conf.conf import CONFIG, _Reason, check_destructive_commands_allowed


@pytest.mark.parametrize("conf_yes", (True, False))
@pytest.mark.parametrize("user_yes", (True, False))
@pytest.mark.parametrize("env_yes", (True, False))
def test_check_destructive_commands(conf_yes, user_yes, env_yes, monkeypatch):
    CONFIG._data = {
        "general": {"enable_destructive_commands_NO_PRODUCTION_zero_guarantees": conf_yes}
    }
    os.environ["JHACK_PROFILE"] = "devmode" if env_yes else ""
    monkeypatch.setattr("sys.stdin", io.StringIO("yes" if user_yes else "no"))

    ret = check_destructive_commands_allowed("foo", _check_only=True)

    if not env_yes:
        if not conf_yes:
            assert ret.reason == _Reason.user
            if user_yes:
                assert ret
            else:
                assert not ret
        else:
            assert ret
            assert ret.reason == _Reason.devmode_perm
    else:
        assert ret
        assert ret.reason == _Reason.devmode_temp
