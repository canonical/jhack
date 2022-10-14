import time
from concurrent.futures import ThreadPoolExecutor
from itertools import chain
from pathlib import Path
from typing import Iterable, Optional, Union

import typer

from jhack.helpers import JPopen, is_k8s_model, juju_status
from jhack.logger import logger as jhack_logger

logger = jhack_logger.getChild("provision")

PROV_SCRIPT_ROOT = Path("~/.cprov/").expanduser().absolute()
# we need the script to live in a location juju can access (juju 3.0 is strictly
# confined, so this is the only safe location for now...)
PROVISION_SCRIPT_TEMPFILE_PATH = Path(
    "~/.local/share/juju/.provision_script.tmp"
).expanduser()
_separator = ";"


def _get_script_temporary_file(script: Union[str, Path]) -> Path:
    tf_path = PROVISION_SCRIPT_TEMPFILE_PATH
    tf_path.touch(mode=0o777)

    pth = Path(script)
    if pth.exists() and pth.is_file():
        logger.debug(f"loaded script file {script}")
        tf_path.write_text(pth.read_text())
    else:
        script_from_root = PROV_SCRIPT_ROOT / script
        if script_from_root.exists() and script_from_root.is_file():
            logger.debug(f"found {script} in `~/.cprov/`")
            tf_path.write_text(script_from_root.read_text())

        else:
            # we'll interpret script as a literal bash script
            logger.debug(f"interpreting {script[:10]}... as an executable script")
            tf_path.write_text(script)

    return tf_path


def _provision_unit(
    unit: str,
    status: dict = None,
    tf_script: Path = PROVISION_SCRIPT_TEMPFILE_PATH,
    container: Optional[str] = "charm",
    timeout=None,
):
    status = status or juju_status(json=True)
    try:
        app_name, unit_n_txt = unit.split("/")
        unit_n = int(unit_n_txt)
    except (ValueError, TypeError) as e:
        logger.debug(e)
        print(
            f"invalid unit name {unit}: expected <app_name:str>/<unit_n:int>,"
            f"e.g. `traefik-k8s/0`, `prometheus/2`."
        )
        return 0

    success = True
    try:
        logger.info("setting workload status to maintenance...")
        wl_status = status["applications"][app_name]["units"][unit]["workload-status"]
        proc = JPopen(
            f"juju exec --unit {unit} -- status-set "
            f"maintenance provisioning... &".split()
        )
        proc.wait()

        logger.info(f"dropping {tf_script} to {unit}:provision")
        proc = JPopen(f"juju scp {tf_script.absolute()} {unit}:/provision".split())
        proc.wait()

        container_arg = (
            f" --container {container}" if (container and is_k8s_model(status)) else ""
        )
        cmd = f"juju ssh{container_arg} {unit} /provision"
        logger.debug(f"cmd: {cmd}")
        proc = JPopen(cmd.split())
        proc.wait(timeout=timeout)

        while proc.returncode is None:
            stdout = proc.stdout.read().decode("utf-8")
            print(stdout)
            time.sleep(0.1)

        if proc.returncode != 0:
            logger.debug(f"process returned with returncode={proc.returncode}")
            logger.error(proc.stdout.read().decode("utf-8"))
            logger.error(proc.stderr.read().decode("utf-8"))
            print(f"failed provisioning {unit}")
            success = False

    finally:
        try:
            # failsafe-try to reset status
            # todo: if status changed in the meantime, don't overwrite it!
            proc = JPopen(
                f"juju exec --unit {unit} -- "
                f'status-set {wl_status["current"]} '
                f'{wl_status.get("message", "")} &'.split()
            )
            proc.wait()
        except:
            pass

    return success


def _check_app_exists(name: str, status: dict):
    return bool(status["applications"].get(name))


def identify(obj: str, status: dict):
    if "/" in obj:
        _check_app_exists(obj.split("/")[0], status)
        return "unit"
    _check_app_exists(obj, status)
    return "app"


def list_units(app, status):
    return list(status["applications"][app]["units"])


def list_apps(status):
    return list(status["applications"])


def _get_provisioner_targets(target: str, status: dict) -> Iterable[str]:
    if target is None:
        return chain(
            *(_get_provisioner_targets(app, status) for app in list_apps(status))
        )
    elif not target:
        return ()
    if _separator in target:
        return chain(
            *(_get_provisioner_targets(tgt, status) for tgt in target.split(_separator))
        )

    is_app = identify(target, status) == "app"
    if is_app:
        return tuple(list_units(target, status))
    else:  # unit
        return (target,)


def _provision(
    target: str,
    script: str = "default",
    container: str = "charm",
    timeout: int = 1000,
    n_proc: int = 8,
    dry_run: bool = False,
):
    tf_script = _get_script_temporary_file(script)
    status = juju_status(json=True)
    targets = tuple(_get_provisioner_targets(target, status))

    if dry_run:
        print(f"[dry run]: with script: {tf_script}")

    try:
        if n_proc and len(targets) > 1:
            logger.debug("running in async mode")
            if dry_run:
                print(f"would provision in parallel:")
                for tgt in targets:
                    print(f"\t{tgt}")
                return

            # This actually runs them sequentially!?
            # pool = Pool()
            # with Pool(processes=n_proc) as pool:
            #     for tgt in targets:
            #         # we don't pass timeout down to _provision_unit,
            #         # instead we give it to the pool worker
            #         res = pool.apply_async(_provision_unit, (tgt,),
            #                                {"container": container,
            #                                 "status": status,
            #                                 "tf_script": tf_script})
            #         outcome = res.get(timeout=timeout)
            #         print(outcome)
            #     pool.terminate()

            executor = ThreadPoolExecutor(max_workers=n_proc)
            tasks = []
            for tgt in targets:
                # we don't pass timeout down to _provision_unit,
                # instead we give it to the pool worker
                tasks.append(
                    (
                        executor.submit(
                            _provision_unit,
                            tgt,
                            container=container,
                            status=status,
                            tf_script=tf_script,
                        ),
                        tgt,
                    )
                )

            for task, tgt in tasks:
                result = task.result(timeout=timeout)
                if not result:
                    # todo: provide some error msg
                    # to debug more easily: try to provision the failed target
                    # on its own, or run the command in sequential mode
                    logger.warning(f"failed to provision {tgt!r}")

        else:
            logger.debug("running in sync mode")
            if dry_run:
                print(f"\twould provision sequentially:")
                if dry_run:
                    for tgt in targets:
                        print(f"\t{tgt}")
                return

            for tgt in targets:
                _provision_unit(
                    tgt,
                    status=status,
                    container=container,
                    timeout=timeout,
                    tf_script=tf_script,
                )

    finally:
        tf_script.unlink()


def provision(
    target: str = typer.Argument(
        None,
        help="The target to provision. Can be an app (provisions all units),"
        " a unit (provisions that unit only), a semicolon-separated list thereof, "
        "or blank (provisions all units)",
    ),
    script: str = typer.Option(
        "default",
        "--script",
        "-s",
        help="The provisioner script. It can either be the path to an executable file "
        f"(presumably a shell script), or a name of a file which will be presumed "
        f"to be in {PROVISION_SCRIPT_TEMPFILE_PATH.parent.absolute()}. "
        f"This is the script that will be run on all to-be-provisioned units.",
    ),
    container: str = typer.Option(
        "charm",
        "--container",
        "-c",
        help="For k8s units, the name of the container to provision.",
    ),
    timeout: int = typer.Option(
        1000,
        "--timeout",
        "-t",
        help="For k8s units, the name of the container to provision.",
    ),
    n_proc: int = typer.Option(
        8,
        "--processes",
        "-p",
        help="Number of processes to spawn. If 0, will provision sequentially.",
    ),
    dry_run: bool = False,
):
    return _provision(
        target=target,
        script=script,
        container=container,
        timeout=timeout,
        n_proc=n_proc,
        dry_run=dry_run,
    )


if __name__ == "__main__":
    _provision("trfk")
