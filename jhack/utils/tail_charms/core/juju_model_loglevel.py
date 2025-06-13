import enum
import shlex
from subprocess import getoutput, run
from typing import Optional

from jhack.conf.conf import CONFIG
from jhack.helpers import JPopen
from jhack.logger import logger as jhack_logger

logger = jhack_logger.getChild(__file__)

BEST_LOGLEVELS = frozenset(("DEBUG", "TRACE"))
AUTO_BUMP_LOGLEVEL_DEFAULT = CONFIG.get("tail", "automatically_bump_loglevel")


class LEVELS(enum.Enum):
    DEBUG = "DEBUG"
    TRACE = "TRACE"
    INFO = "INFO"
    ERROR = "ERROR"


def model_loglevel(model: str = None):
    _model = f"-m {model} " if model else ""
    try:
        lc = JPopen(f"juju model-config {_model}logging-config".split())
        lc.wait()
        if lc.returncode != 0:
            logger.info(
                "no model config: maybe there is no current model? defaulting to WARNING"
            )
            return "WARNING"  # the default

        logging_config = lc.stdout.read().decode("utf-8")
        for key, val in (cfg.split("=") for cfg in logging_config.split(";")):
            if key == "unit":
                val = val.strip()
                if val not in BEST_LOGLEVELS:
                    logger.warning(
                        f"unit loglevel is {val}, which means tail will not be able to "
                        f"track Operator Framework debug logs for deferrals, reemittals, etc. "
                        f"Using juju uniter logs to track emissions. To fix this, run "
                        f"`juju model-config logging-config=<root>=WARNING;unit=TRACE`"
                    )
                return val

    except Exception as e:
        logger.error(
            f"failed to determine model loglevel: {e}. Guessing `WARNING` for now."
        )
    return "WARNING"  # the default


def bump_loglevel() -> Optional[str]:
    cmd = "juju model-config logging-config"
    old_config = getoutput(cmd).strip()
    cfgs = old_config.split(";")
    new_config = []

    for cfg in cfgs:
        if "ERROR" in cfg:
            logger.error(f"failed bumping loglevel to unit=DEBUG: {cfg}")
            return

        n, lvl = cfg.split("=")
        if n == "unit":
            logger.debug(f"existing unit-level logging config found: was {lvl}")
            continue
        new_config.append(cfg)

    new_config.append("unit=DEBUG")

    cmd = f"juju model-config logging-config={';'.join(new_config)!r}"
    run(shlex.split(cmd))
    return old_config


def debump_loglevel(previous: str):
    cmd = f"juju model-config logging-config={previous!r}"
    run(shlex.split(cmd))
