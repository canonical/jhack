import contextlib
import shlex
from subprocess import getoutput, run
from typing import Optional

from jhack import helpers
from jhack.conf.conf import CONFIG
from jhack.logger import logger as jhack_logger

logger = jhack_logger.getChild(__file__)

AUTO_BUMP_LOGLEVEL_DEFAULT = CONFIG.get("tail", "automatically_bump_loglevel")


def bump_loglevel(model: Optional[str] = None) -> Optional[str]:
    """Try to bump the model loglevel"""
    _model = f" --model {model}" if model else ""
    cmd = f"juju model-config{_model} logging-config"
    old_config = getoutput(cmd).strip()
    cfgs = old_config.split(";")
    new_config = []

    for cfg in cfgs:
        if "ERROR" in cfg:
            logger.error(f"failed bumping loglevel to unit=DEBUG: {cfg}")
            return None

        n, lvl = cfg.split("=")
        if n == "unit":
            logger.debug(f"existing unit-level logging config found: was {lvl}")
            continue
        new_config.append(cfg)

    new_config.append("unit=DEBUG")

    cmd = f"juju model-config logging-config={';'.join(new_config)!r}"
    run(shlex.split(cmd))
    return old_config


def debump_loglevel(previous: str, model: Optional[str] = None):
    _model = f" --model {model}" if model else ""
    cmd = f"juju model-config{_model} logging-config={previous!r}"
    run(shlex.split(cmd))


@contextlib.contextmanager
def juju_loglevel_bumpctx(model: str, flag: bool):
    if flag:
        pre = bump_loglevel(model)
        if pre is None:
            # this usually means the model doesn't exist.
            try:
                helpers.juju_status(model=model)
            except helpers.GetStatusError:
                if model:
                    exit(
                        f"unable to connect to model {model}. "
                        f"Does the model exist on the current controller?"
                    )
                else:
                    exit("unable to connect to current juju model. Are you switched to one?")
        try:
            yield
        finally:
            debump_loglevel(pre, model)
    else:
        yield
