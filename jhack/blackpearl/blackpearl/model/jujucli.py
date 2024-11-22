#!/usr/bin/env python3
# Copyright 2024 Pietro Pasotti (@ppasotti)
# See LICENSE file for licensing details.


from logging import getLogger

import json
import random
import string
import subprocess
import time
from contextlib import contextmanager
from datetime import timedelta
from enum import Enum
from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess
from typing import Callable, Dict, Iterable, List, Optional, Tuple, Union, Any

logger = getLogger("juju")


class JujuError(Exception):
    """Base class for custom exceptions raised by this module."""


class WaitFailedError(JujuError):
    """Raised when the ``Juju.wait()`` fail condition triggers."""


class StatusError(JujuError):
    """Raised when the ``Juju.status()`` fails."""


class WorkloadStatus(str, Enum):
    """Juju unit/app workload status."""

    active = "active"
    waiting = "waiting"
    maintenance = "maintenance"
    blocked = "blocked"
    error = "error"
    unknown = "unknown"


class AgentStatus(str, Enum):
    """Juju unit/app agent status."""

    idle = "idle"
    executing = "executing"
    allocating = "allocating"
    error = "error"


class Status(dict):
    def juju_status(self, application: str):
        """Get a mapping from unit name to active/idle, unknown/executing..."""
        units = self["applications"][application]["units"]
        return {u: units[u]["juju-status"]["current"] for u in units}

    def app_status(self, application: str) -> WorkloadStatus:
        """Application status."""
        return self["applications"][application]["application-status"]["current"]

    def workload_status(self, application: str) -> Dict[str, WorkloadStatus]:
        """Get a mapping from unit name to active/unknown/error..."""
        units = self["applications"][application]["units"]
        return {u: units[u]["workload-status"]["current"] for u in units}

    def agent_status(self, application: str) -> Dict[str, AgentStatus]:
        """Get a mapping from unit name to idle/executing/error..."""
        units = self["applications"][application]["units"]
        return {u: units[u]["juju-status"]["current"] for u in units}

    def _sanitize_apps_input(self, apps: Iterable[str]) -> Tuple[str, ...]:
        if not apps:
            return tuple(self["applications"])
        if isinstance(apps, str):
            # str is Iterable[str]...
            return (apps,)
        return tuple(apps)

    def _check_status_all(
        self, apps: Iterable[str], status: str, status_getter=Callable[["Status"], str]
    ):
        for app in self._sanitize_apps_input(apps):
            statuses = status_getter(app)
            if not statuses:  # avoid vacuous quantification
                return False

            if not all(us == status for us in statuses.values()):
                return False
        return True

    def _check_status_any(
        self, apps: Iterable[str], status: str, status_getter=Callable[["Status"], str]
    ):
        for app in self._sanitize_apps_input(apps):
            statuses = status_getter(app)
            if not statuses:  # avoid vacuous quantification
                # logically this should be false, but for consistency with 'all'...
                return True

            if any(us == status for us in statuses.values()):
                return True
        return False

    def all_workloads(self, apps: Iterable[str], status: WorkloadStatus):
        """Return True if all workloads of these apps (or all apps) are in this status."""
        return self._check_status_all(apps, status, status_getter=self.workload_status)

    def any_workload(self, apps: Iterable[str], status: WorkloadStatus):
        """Return True if any workload of these apps (or all apps) are in this status."""
        return self._check_status_any(apps, status, status_getter=self.workload_status)

    def all_agents(self, apps: Iterable[str], status: WorkloadStatus):
        """Return True if all agents of these apps (or all apps) are in this status."""
        return self._check_status_all(apps, status, status_getter=self.agent_status)

    def any_agent(self, apps: Iterable[str], status: WorkloadStatus):
        """Return True if any agent of these apps (or all apps) are in this status."""
        return self._check_status_any(apps, status, status_getter=self.agent_status)

    def get_leader_name(self, app_name: str) -> Optional[str]:
        """Return the leader for this application."""
        units = self["applications"][app_name].get("units")
        if not units:
            logger.error(f"get_leader_name: no units found for {app_name}")
            return

        leaders = [unit for unit, meta in units.items() if meta.get("leader")]
        if leaders:
            return leaders[0]

        logger.error("get_leader_name: no leader elected yet")
        return

    def get_application_ip(self, app_name: str) -> Optional[str]:
        """Return the juju application IP."""
        address = self["applications"][app_name].get("address")
        if not address:
            logger.error(f"get_application_ip: no address assigned yet to {app_name}")
        return address

    def get_unit_ips(self, app_name: str) -> Dict[str, str]:
        """Return the juju unit IP for all units of this app."""
        units = self["applications"][app_name].get("units")
        if not units:
            logger.error(f"get_leader_name: no units found for {app_name}")
        out = {}
        for unit, meta in units.items():
            address = meta.get("address")
            if address:
                out[unit] = address
            else:
                logger.error(f"get_unit_ips: no address assigned yet to {unit}")

        return out


class _JujuConfigBase:
    def __init__(self, raw: dict):
        self.raw = raw

    def get(self, key: str) -> Union[int, str, bool, float, None]:
        meta = self.raw[key]
        if meta["source"] in {"unset", "default"}:
            out = meta.get("default")
        else:
            out = meta["value"]

        if out == "''":
            return None

        return out


class _ApplicationConfig(_JujuConfigBase):
    pass


class _CharmConfig(_JujuConfigBase):
    pass


class Config:
    """Juju config wrapper."""

    def __init__(self, raw: dict):
        self.raw = raw

    @property
    def charm(self):
        return _CharmConfig(self.raw["settings"])

    @property
    def app(self):
        return _ApplicationConfig(self.raw["application-config"])


class JujuLogLevel(str, Enum):
    """Juju loglevels enum."""

    TRACE = "TRACE"
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


def generate_random_model_name(prefix: str = "test-", suffix: str = ""):
    name = "test-"
    for _ in range(15):
        name += random.choice(string.ascii_lowercase)
    return name


class Juju:
    """Juju CLI wrapper for in-model operations."""

    def __init__(self, model: str = None):
        self.model = model

    def model_name(self):
        """Get the name of the current model."""
        return self.model or self.status()["model"]["name"]

    def status(self, quiet: bool = False) -> Status:
        """Fetch the juju status."""
        args = ["status", "--format", "json"]
        try:
            result = self.cli(*args, quiet=quiet)
        except:
            result = None

        if not result:
            raise StatusError(f"cannot get status for {self.model}")

        return Status(json.loads(result.stdout))

    def application_config_get(self, app) -> Config:
        """Fetch the current configuration of an application."""
        args = ["config", app, "--format", "json"]
        result = self.cli(*args)
        return Config(json.loads(result.stdout))

    def application_config_set(self, app, config: Dict[str, Union[bool, str]]):
        """Update the configuration of an application."""
        if not config:
            raise ValueError("cannot call application_config_set with an empty config")
        args = ["config", app]

        for k, v in config.items():
            if isinstance(v, bool):
                args.append(f"{k}={str(v).lower()}")
            elif v is None:  # unset
                args.append(f"{k}=''")
            else:
                args.append(f"{k}={str(v)}")
        self.cli(*args)

    def model_config_get(self) -> Dict[str, Dict[str, str]]:
        """Get this model's configuration."""
        result = self.cli("model-config", "--format", "json")
        # if used without args, returns the current config
        return json.loads(result.stdout)

    def model_config_set(self, config: Dict[str, Union[bool, str]]):
        """Update this model's configuration."""
        args = ["model-config"]
        for k, v in config.items():
            if isinstance(v, bool):
                args.append(f"{k}={str(v).lower()}")
            else:
                args.append(f"{k}={str(v)}")
        self.cli(*args)

    @contextmanager
    def fast_forward(
        self, fast_interval: str = "5s", slow_interval: Optional[str] = None
    ):
        """Context manager to temporarily speed up update-status hook execution."""
        update_interval_key = "update-status-hook-interval"
        if slow_interval:
            interval_after = slow_interval
        else:
            # don't ask me why it's capitalized
            interval_after = self.model_config_get()[update_interval_key]["Value"]

        self.model_config_set({update_interval_key: fast_interval})
        yield
        self.model_config_set({update_interval_key: interval_after})

    def add_unit(self, app: str, *, n: int = 1):
        """Add one or multiple units to an application."""
        args = ["add-unit", "-n", str(n), app]
        return self.cli(*args)

    def remove_unit(
        self,
        app: str,
        *,
        n: int = 1,
        destroy_storage: bool = True,
        wait: bool = False,
        force: bool = False,
    ):
        """Remove one or multiple units from an application."""
        args = ["remove-unit", "--num-units", str(n), "--no-prompt"]
        if destroy_storage:
            args.append("--destroy-storage")
        if not wait:
            args.append("--no-wait")
        if force:
            args.append("--force")
        args.append(app)
        return self.cli(*args)

    def remove_application(
        self,
        app: str,
        destroy_storage: bool = True,
        wait: bool = False,
        force: bool = False,
    ):
        """Remove one or multiple units from an application."""
        args = ["remove-application", "--no-prompt"]
        if destroy_storage:
            args.append("--destroy-storage")
        if not wait:
            args.append("--no-wait")
        if force:
            args.append("--force")
        args.append(app)
        return self.cli(*args)

    def deploy(
        self,
        charm: str | Path,
        *,
        alias: str | None = None,
        channel: str | None = None,
        config: None | Dict[str, str] = None,
        resources: None | Dict[str, str] = None,
        trust: bool = False,
        scale: int = 1,
    ):
        """Deploy a charm."""
        args = ["deploy", str(charm)]

        if alias:
            args = [*args, alias]

        if scale:
            args = [*args, "--num-units", scale]

        if channel:
            args = [*args, "--channel", channel]

        if config:
            for k, v in config.items():
                args = [*args, "--config", f"{k}={v}"]

        if resources:
            for k, v in resources.items():
                args = [*args, "--resource", f"{k}={v}"]

        if trust:
            args = [*args, "--trust"]

        return self.cli(*args)

    def integrate(self, requirer: str, provider: str):
        """Integrate two application endpoints."""
        args = ["integrate", requirer, provider]
        return self.cli(*args)

    def disintegrate(self, requirer: str, provider: str):
        """Remove an integration."""
        args = ["remove-relation", requirer, provider]
        return self.cli(*args)

    def scp(
        self, unit: str, origin: Union[str, Path], destination: Union[str, Path] = None
    ):
        """Juju scp wrapper."""
        args = [
            "scp",
            "-m",
            self.model,
            str(origin),
            f"{unit}:{destination or Path(origin).name}",
        ]
        return self.cli(*args)

    def ssh(self, unit: str, cmd: str):
        """Juju ssh wrapper."""
        args = ["ssh", "-m", self.model, unit, cmd]
        return self.cli(*args)

    def run(self, app: str, action: str, params: Dict[str, str], unit_id: int = None):
        """Run an action."""
        target = app + f"/{unit_id}" if unit_id is not None else app + "/leader"
        args = ["run", "--format", "json", target, action]

        for k, v in params.items():
            args.append(f"{k}={v}")

        act = self.cli(*args)
        result = json.loads(act.stdout)

        # even if you juju run foo/leader, the output will be for its specific ID: {"foo/0":...}
        return list(result.values())[0]

    def display_status(self, quiet: bool = True):
        """Print the `juju status` to stdout."""
        print(self.cli("status", "--relations", quiet=quiet).stdout)

    def wait(  # noqa: C901
        self,
        timeout: int,
        soak: int = 10,
        stop: Optional[Callable[[Status], bool]] = None,
        fail: Optional[Callable[[Status], bool]] = None,
        refresh_rate: float = 1.0,
        print_status_every: Optional[int] = 60,
        quiet: bool = True,
    ):
        """Wait for the stop/fail condition to be met.

        Examples:
        >>> Juju("mymodel").wait(
        ...   stop=lambda s:s.all("foo", WorkloadStatus.active),
        ...   fail=lambda s:s.any("foo", WorkloadStatus.blocked),
        ...   timeout=2000)

        This will block until all "foo" units go to "active" status, and raise if any goes
         to "blocked" before the stop condition is met.
        """
        start = time.time()
        soak_time = timedelta(seconds=soak)
        stop_condition_first_hit: Optional[float] = None
        last_status_printed_time = (
            0  # number of seconds since the epoch, that is, very long ago
        )
        if not (stop or fail):
            raise ValueError(
                "pass a `stop` or a `fail` condition; "
                "else we don't know what to wait for."
            )

        logger.info(f"Waiting for conditions; stop={stop}, fail={fail}")

        try:
            while time.time() - start < timeout:
                try:
                    status = self.status(quiet=quiet)

                    # if the time elapsed since the last status-print is less than print_status_every,
                    # we print out the status.
                    if print_status_every is not None and (
                        (abs(last_status_printed_time - time.time()))
                        >= print_status_every
                    ):
                        last_status_printed_time = time.time()
                        self.display_status()

                    if stop:
                        if stop(status):
                            if not stop_condition_first_hit:
                                stop_condition_first_hit = time.time()
                                logger.debug("started soak period")
                                continue

                            if (
                                time.time() - stop_condition_first_hit
                                >= soak_time.seconds
                            ):
                                logger.debug("soak successfully terminated")
                                return True
                        else:
                            if stop_condition_first_hit:
                                logger.debug(
                                    "soak interrupted: stop condition no longer met"
                                )
                                stop_condition_first_hit = None

                    if fail and fail(status):
                        raise WaitFailedError("fail condition met during wait")

                except WaitFailedError:
                    raise

                except Exception as e:
                    logger.debug(f"error encountered while waiting: {e}")
                    pass

                time.sleep(refresh_rate)
            raise TimeoutError(
                "timeout hit before any of the pass/fail conditions were met"
            )

        finally:
            # before we return, whether it's an exception or a True, we print out the status.
            self.display_status()

    def debug_log(
        self,
        *,
        replay: bool = False,
        tail: bool = False,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
        include_module: Optional[List[str]] = None,
        exclude_module: Optional[List[str]] = None,
        include_label: Optional[List[str]] = None,
        exclude_label: Optional[List[str]] = None,
        ms: Optional[bool] = False,
        date: Optional[bool] = False,
        level: JujuLogLevel = JujuLogLevel.DEBUG,
    ) -> str:
        """Get the juju debug-log."""
        args = ["debug-log"]

        if tail:
            args.append("--tail")
        else:
            args.append("--no-tail")

        if level is not None:
            args.append(f"--level={level.value}")

        # boolean flags
        _bool_str = {True: "true", False: "false"}
        for flagname, value in (
            ("ms", ms),
            ("date", date),
            ("replay", replay),
        ):
            if value is not None:
                args.append(f"--{flagname}={_bool_str[value]}")

        # include/exclude sequences
        for flagname, values in (
            ("include", include),
            ("exclude", exclude),
            ("include-module", include_module),
            ("exclude-module", exclude_module),
            ("include-label", include_label),
            ("exclude-label", exclude_label),
        ):
            if not values:
                continue
            for value in values:
                args.append(f"--{flagname}={value}")

        return self.cli(*args).stdout

    def destroy_model(
        self,
        *,
        model_name: str = None,
        destroy_storage: bool = False,
        force: bool = False,
    ):
        """Destroy this or another model."""
        args = ["destroy-model", "--no-prompt"]
        if destroy_storage:
            args.append("--destroy-storage")
        if force:
            args.append("--force")
        args.append(model_name or self.model_name())
        return self.cli(*args, add_model_flag=False)

    def controllers(self) -> Dict[str, Any]:
        """Get all controllers json datastructure."""
        return json.loads(
            self.cli("controllers", "--format", "json", add_model_flag=False).stdout
        )["controllers"]

    def models(self, controller: str) -> List[Any]:
        """Get all models for this controller."""
        return json.loads(
            self.cli(
                "models",
                "--controller",
                controller,
                "--format",
                "json",
                add_model_flag=False,
            ).stdout
        )["models"]

    def cli(
        self, *args, add_model_flag: bool = True, quiet: bool = False
    ) -> CompletedProcess:
        """Raw cli access.

        Thin wrapper on top of Popen, but appends `-m <model name>` to the command args
        if this Juju is bound to a model.
        """
        if "--force" in args:
            logger.warning("running commands with --force is, like, **super bad**")

        if add_model_flag and "-m" not in args and self.model:
            args = [*args, "-m", self.model]

        args_ = list(map(str, ["/snap/bin/juju", *args]))
        if not quiet:
            logger.info(f"executing {' '.join(args_)!r}")

        try:
            proc = subprocess.run(
                args_,
                check=False,  # we want to expose the stderr on failure
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"NO_COLOR": "true"},
            )
        except CalledProcessError:
            logger.error(f"command {' '.join(args_)!r} errored out")
            raise

        if proc.returncode:
            logger.info(f"command {' '.join(args_)!r} errored out.")
            logger.info(f"\tstdout:\n{proc.stdout}")
            logger.info(f"\tstderr:\n{proc.stderr}")

        # now we let it raise
        proc.check_returncode()
        return proc

    def switch(self, model: Optional[str] = None) -> "Juju":
        """Switch to this model or a different one."""
        target_model = model or self.model
        if not target_model:
            raise RuntimeError("cannot `switch()` an unbound model")

        self.cli("switch", target_model, add_model_flag=False)
        return Juju(target_model)

    def add_model(self, model: Optional[str] = None, switch: bool = False) -> "Juju":
        """Add this or a new model to the current controller."""
        target_model = model or self.model
        if not target_model:
            raise RuntimeError("cannot `switch()` an unbound model")

        args = ["add-model", target_model]
        if switch:
            args.append("--no-switch")
        self.cli(*args, add_model_flag=False)
        return Juju(target_model)


if __name__ == "__main__":
    print(Juju().status().get_application_ip("tempo"))
    print(Juju().status().get_leader_name("tempo"))
    print(Juju().status().get_unit_ips("tempo"))
