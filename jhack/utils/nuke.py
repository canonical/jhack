import re
import signal
from contextlib import contextmanager
from dataclasses import dataclass
from multiprocessing.pool import ThreadPool
from subprocess import PIPE
from time import sleep
from typing import Callable, List, Literal, Optional

import typer
from rich.align import Align
from rich.console import Console
from rich.style import Style
from rich.text import Text

from jhack.conf.conf import CONFIG
from jhack.helpers import JPopen, current_model, juju_models, juju_status, list_models
from jhack.logger import logger

logger = logger.getChild("nuke")

ASK_FOR_CONFIRMATION = CONFIG["nuke"]["ask_for_confirmation"]
_Color = Optional[Literal["auto", "standard", "256", "truecolor", "windows", "no"]]
ATOM = "⚛"
ICBM = f"~]=={ATOM}❯"
COLOR_MAP = {
    "model": "red",
    "relation": "cyan",
    "app": "#ebb134",
}
NUKE_ASCII_ART = """
                             ____
                     __,-~~/~    `---.
                   _/_,---(      ,    )
               __ /        <    /   )  \___
- ------===;;;'====------------------===;;;===----- -  -
                  \/  ~"~"~"~"~"~\~"~)~"/
                  (_ (   \  (     >    \)
                   \_( _ <         >_>'
                      ~ `-i' ::>|--"
                          I;|.|.|
                         <|i::|i|`.
                        (` ^'"`-' ")
"""


class TimeoutException(Exception):
    pass


@contextmanager
def timeout(seconds, raise_=False):
    def signal_handler(signum, frame):
        raise TimeoutException("Timed out!")

    signal.signal(signal.SIGALRM, signal_handler)
    signal.alarm(seconds)
    try:
        yield
    except TimeoutException as e:
        if raise_:
            raise e
        return None
    finally:
        signal.alarm(0)


@dataclass
class Endpoints:
    provider: str
    requirer: str


@dataclass
class Nukeable:
    name: str
    type: Literal["model", "app", "relation"]

    # only applies to relations
    endpoints: Endpoints = None

    # model the nukeable is in, only applies to apps and relations
    model: str = None

    def __repr__(self):
        if self.type == "model":
            return f"model {self.name!r}"
        elif self.type == "app":
            return f"app {self.name!r} ({self.model})"
        else:  # relation
            return f"relation {self.endpoints.provider!r} --> {self.endpoints.requirer}"


def _get_models(filter_):
    """List of existing models."""
    models = juju_models()
    found = 0
    _models = []
    for line in models.split("\n"):
        if line.startswith("Model "):
            found = 1
            continue
        if found and not line:
            break  # end of section
        if found:
            model_name = line.split()[0]
            if filter_(model_name):
                _models.append(model_name)
    if "controller" in _models:
        _models.remove("controller")  # shouldn't try to nuke that one!
    return tuple(Nukeable(m, "model") for m in _models)


def _get_apps_and_relations(
    model: Optional[str],
    borked: bool,
    filter_: Callable[[str], bool],
    include_apps: bool = True,
    include_relations: bool = True,
) -> List[Nukeable]:
    logger.info("gathering apps and relations")

    status = juju_status("", model)
    if not status:
        return []

    apps = 0
    relation = 0
    nukeables = []
    for line in status.split("\n"):
        if line.startswith("App "):
            apps = 1
            continue

        if line.startswith("Unit "):
            apps = 0
            continue

        if line.startswith("Relation "):
            relation = 1
            apps = 0
            continue

        if not line.strip():
            continue

        logger.debug(f"checking {line}")
        if apps and include_apps:
            logger.debug(f"checking {line}")
            if borked and "active" in line:
                logger.debug(f"skipping non-borked app")
                continue
            entity_name = line.split()[0].strip("*")
            if "/" in entity_name:
                logger.debug(f"skipping unit {entity_name}")
                # unit; can't nuke those yet
                continue
            if filter_(entity_name):
                logger.debug(f"nukeable identified: {entity_name} (app)")
                nukeables.append(Nukeable(entity_name, "app", model=model))
            else:
                logger.debug(f"nukeable skipped: {entity_name} (app)")

        if relation and include_relations:
            prov, req, *_ = re.split(r"\s+", line)
            eps = Endpoints(prov.strip(), req.strip())
            if filter_(eps.provider) or filter_(eps.requirer):
                logger.debug(f"nukeable identified: {eps} (rel)")
                nukeables.append(Nukeable(f"{prov} {req}", "relation", endpoints=eps))
            else:
                logger.debug(f"nukeable skipped: {eps} (rel)")

    return nukeables


def _gather_nukeables(
    obj: Optional[str], model: Optional[str], borked: bool, selectors: str = ""
):
    logger.debug(f"Gathering nukeables for {obj!r} with _selectors = {selectors!r}")

    globber = lambda s: s.startswith(obj)

    if isinstance(obj, str) and ("*" in obj or "!" in obj):
        logger.info("globbing detected; analyzing pattern")

        if "*" in obj and "!" in obj:
            raise RuntimeError("combinations of ! and * not supported.")

        if obj.startswith("!"):
            globber = lambda s: obj.strip("!") == s
        elif "!" in obj:
            raise RuntimeError("! is only supported at the start of the name.")

        if obj.startswith("*") and obj.endswith("*") and obj != "*":
            globber = lambda s: obj.strip("*") in s
        elif obj.startswith("*"):
            globber = lambda s: s.endswith(obj.strip("*"))
        elif obj.endswith("*"):
            globber = lambda s: s.startswith(obj.strip("*"))

        obj = obj.strip("*!")

    nukeables: List[Nukeable] = []

    if "a" in selectors or "r" in selectors:
        logger.info(f"gathering apps and relations ({selectors})")
        nukeables.extend(
            _get_apps_and_relations(
                model or current_model(),
                borked=borked,
                filter_=globber,
                include_apps="a" in selectors,
                include_relations="r" in selectors,
            )
        )

    # if we passed a model, we mean 'nuke something in that model'
    # otherwise, we may be interested in nuking the models themselves.
    if not model and "m" in selectors:
        logger.info("gathering models")
        for model_ in list_models(strip_star=True):
            if model_ == "controller":
                continue
            if globber(model_):
                logger.info(f"collected {model_} for nukage")
                nukeables.append(Nukeable(model_, "model"))

    return nukeables


def _nuke(
    obj: Optional[str],
    model: Optional[str] = None,
    borked: bool = False,
    selectors: Optional[str] = None,
    n: int = None,
    dry_run: bool = False,
    color: _Color = "auto",
):
    if obj is None and not borked and not selectors:
        logger.info("No object | selectors provided, we'll nuke the current model.")
        nukeables = [Nukeable(current_model(), "model")]
    else:
        if obj is None:
            # means we passed selectors:
            assert selectors, "invalid usage"
            obj = ""  # FIXME: kinda hacky

        if obj == "*" and selectors is None:
            # nuke * === nuke all applications.
            # That's the most common target.
            _selectors = {"a"}
        elif borked:
            _selectors = {"a"}
        else:
            SELECTORS = "amr"
            _selectors = set(selectors or SELECTORS)  # all
            for char in SELECTORS:
                if char.upper() in _selectors:
                    _selectors.remove(char.upper())
                    _selectors.remove(char)

        nukeables = _gather_nukeables(
            obj, model, borked=borked, selectors="".join(_selectors)
        )
        logger.debug(f"Gathered: {nukeables}")

    nukes = []
    nuked_apps = set()
    nuked_models = set()

    for nukeable in tuple(nukeables):
        logger.info(f"collecting for nukage: {nukeable}")
        if nukeable.type == "model":
            nuked_models.add(nukeable.name)
            nukes.append(
                f"juju destroy-model {nukeable.name} "
                f"--force --no-wait --destroy-storage -y"
            )

        elif nukeable.type == "app":
            nuked_apps.add(nukeable.name)

            assert nukeable.model, f"app {nukeable.name} has unknown model"
            if nukeable.model in nuked_models:
                nukeables.remove(nukeable)
                continue

            nukes.append(
                f"juju remove-application {nukeable.name} " f"--force --no-wait"
            )

        elif nukeable.type == "relation":
            # if we're already nuking either app, let's skip nuking the relation
            assert nukeable.endpoints, f"relation {nukeable.name} has unknown endpoints"
            provider = nukeable.endpoints.provider
            requirer = nukeable.endpoints.requirer
            if (
                provider.split(":")[0] in nuked_apps
                or requirer.split(":")[0] in nuked_apps
            ):
                nukeables.remove(nukeable)
                continue

            nukes.append(f"juju remove-relation {provider} {requirer}")

        else:
            raise ValueError(nukeable.type)

    if n is not None:
        if n != (real_n := len(nukeables)):
            logger.debug(
                f"Unexpected number of nukeables; " f"expected {n}, got: {nukeables}"
            )
            for nukeable in nukeables:
                print(f"would {ATOM} {nukeable}")
            word = "less" if n > real_n else "more"
            print(f"\nThat is {word} than what you expected. Aborting...")
            return

    if not nukeables:
        print(f"Nothing to {ATOM}.")
        return

    if dry_run:
        for nukeable, nuke in zip(nukeables, nukes):
            print(f"would {ATOM} {nukeable} with {nuke}")
        return

    if ASK_FOR_CONFIRMATION:
        print("Are you sure you want to nuke:")
        for nukeable, nuke in zip(nukeables, nukes):
            print(f"\t{ATOM} {nukeable}")

        try:
            if typer.prompt("Please confirm", default="y",
                            show_default=True,
                            show_choices=True) not in ["y", ""]:  # ENTER or "y"
                print("Aborted.")
                return
        except typer.Abort:
            print("\nAborted.")
            return

    if color == "no":
        color = None

    console = Console(color_system=color)
    print_centered = lambda s: console.print(Align(s, align="center"))

    def fire(nukeable: Nukeable, nuke: str):
        """defcon 5"""
        _atom = Style(bold=True, color="green")

        nukeable_name = nukeable.name
        if not nukeable.type == "model":
            nukeable_name += f" ({nukeable.model})"

        to_nuke = Style(color=COLOR_MAP[nukeable.type])
        text = (
            Text(ICBM + " " * 2)
            .append(nukeable_name, to_nuke)
            .append("  " + ATOM, _atom)
        )

        print_centered(text)

        # todo split model nukes to a separate process and pass there shell=True
        logger.debug(f"nuking {nukeable} with {nuke}")
        proc = JPopen(nuke.split(" "))
        proc.wait()
        while proc.returncode is None:
            sleep(0.1)
        if proc.returncode != 0:
            print(
                f"something went wrong nuking {nukeable.name};"
                f'stdout={proc.stdout.read().decode("utf-8")}'
                f'stderr={proc.stderr.read().decode("utf-8")}'
            )
        else:
            logger.debug(f"hit and sunk")

    print_centered(Text(NUKE_ASCII_ART, style=Style(dim=True, blink=True, bold=True)))

    tp = ThreadPool()
    results = []
    for nukeable, nuke in zip(nukeables, nukes):
        logger.debug(f"firing {nuke} {ICBM} {nukeable}")
        res = tp.apply_async(fire, (nukeable, nuke))
        results.append((res, nukeable, nuke))

    with timeout(1):
        tp.close()
        tp.join()

    for res, nkbl, nk in results:
        if not res.ready():
            print_centered(f"{ICBM} {nkbl} still in flight")
        else:
            if not res.successful():
                print_centered(
                    f"nuke {nk!r} {ICBM} {nkbl!r} failed; someone doesn't want to die"
                )

    if not dry_run:
        print_centered(Text("✞ RIP ✞", style=Style(bold=True, dim=True)))


def nuke(
    what: List[str] = typer.Argument(None, help=f"What to {ATOM}."),
    selectors: str = typer.Option(
        None,
        "-s",
        "--select",
        help=f"Selector specifiers to choose what to {ATOM}."
        f"A lower-case letter indicates `include`, "
        f"an upper-case one indicates `exclude`. \n\n"
        f"m := models; a := apps; r := relations\n\n"
        f"Examples:"
        f"`ma` = only include models and apps in the target selection (equivalent to `R`).\n"
        f"`AR` = exclude models and relations (equivalent to `m`)",
    ),
    model: Optional[str] = typer.Option(
        None, "-m", "--model", help="The model. Defaults to current model."
    ),
    n: Optional[int] = typer.Option(
        None,
        "-n",
        "--number",
        help="Exact number of things you're expectig to get nuked." "Safety first.",
    ),
    borked: bool = typer.Option(
        None,
        "-b",
        "--borked",
        help="Nukes all borked applications in current or target model.",
    ),
    dry_run: bool = typer.Option(
        None, "--dry-run", help="Do nothing, print out what would have happened."
    ),
    color: Optional[str] = typer.Option(
        "auto",
        "-c",
        "--color",
        help="Color scheme to adopt. Supported options: "
        "['auto', 'standard', '256', 'truecolor', 'windows', 'no'] "
        "no: disable colors entirely.",
    ),
):
    """Surgical carpet bombing tool.

    Attempts to guess what you want to burn, and rains holy vengeance upon it.

    Examples:
        $ jhack nuke
        will vanquish the current model
        $ jhack nuke test-foo-*
        will bomb all nukeables starting with `test-foo-` , including:
         - models
         - applications
         - relations
        $ jhack nuke --model foo bar-*
        will bomb all nukeables starting with `bar-` in model foo. As above.
        $ jhack nuke -n=2 *foo*
        will blow up the two things it can find that contain the substring "foo"

    Nuke ascii art by Bill March from https://www.asciiart.eu/weapons/explosives
    """
    logger.info("starting jhack nuke")

    if n is not None:
        assert n > 0, f"nonsense: {n}"
        if not len(what) == 1:
            print("You cannot use `-n` with multiple targets.")
            return
    if selectors != "a" and borked:
        print("borked implies selector=`a`")
        return
    kwargs = dict(
        model=model,
        borked=borked,
        selectors=selectors,
        n=n,
        dry_run=dry_run,
        color=color,
    )
    if not what:
        _nuke(None, **kwargs)
    for obj in what:
        _nuke(obj, **kwargs)


if __name__ == "__main__":
    _nuke("ceilo", dry_run=True)
