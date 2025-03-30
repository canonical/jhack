import re
import signal
from contextlib import contextmanager
from dataclasses import dataclass
from multiprocessing.pool import ThreadPool
from time import sleep
from typing import Callable, List, Literal, Optional

import typer
from rich.align import Align
from rich.console import Console
from rich.style import Style
from rich.text import Text

from jhack.conf.conf import CONFIG, check_destructive_commands_allowed
from jhack.helpers import (
    GetStatusError,
    JPopen,
    get_current_model,
    get_models,
    juju_status,
)
from jhack.logger import logger

logger = logger.getChild("nuke")

ASK_FOR_CONFIRMATION = CONFIG.get("nuke", "ask_for_confirmation")
GENTLY = CONFIG.get("nuke", "gently")
BLINK = CONFIG.get("nuke", "blink")

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

NUKE_GENTLY_ASCII_ART = """                       
                \`*-.                   
                 )  _`-.                
                .  : `. .               
                : _   '  \              
                ; *` _.   `*-._         
                `-.-'          `-.      
                  ;       `       `.    
                  :.       .        \   
                  . \  .   :   .-'   .  
                  '  `+.;  ;  '      :  
                  :  '  |    ;       ;-.
       __         ; '   : :`-:     _.`* ;
     (juju)    .*' /  .*' ; .*`- +'  `*'
   ~~~~^^      `*-*   `*-*  `*-*'       
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


def _get_apps_and_relations(
    model: Optional[str],
    borked: bool,
    filter_: Callable[[str], bool],
    include_apps: bool = True,
    include_relations: bool = True,
) -> List[Nukeable]:
    logger.info("gathering apps and relations")

    try:
        status = juju_status("", model)
    except GetStatusError:
        logger.error(
            f"nuke attempted to get the status of {model} but the model is probably dead already."
        )
        return []

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

        if line.startswith("Integration ") or line.startswith("Relation "):
            relation = 1
            apps = 0
            continue

        if not line.strip():
            continue

        logger.debug(f"checking {line}")
        if apps and include_apps:
            logger.debug(f"checking {line}")
            if borked and "active" in line:
                logger.debug("skipping non-borked app")
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
    obj: Optional[str],
    model: Optional[str],
    borked: bool,
    selectors: str = "",
    cur_model: Optional[str] = None,
):
    logger.debug(f"Gathering nukeables for {obj!r} with _selectors = {selectors!r}")

    def globber(s):
        return s.startswith(obj)

    if isinstance(obj, str) and ("*" in obj or "!" in obj):
        logger.info("globbing detected; analyzing pattern")

        if "*" in obj and "!" in obj:
            raise RuntimeError("combinations of ! and * not supported.")

        if obj.startswith("!"):

            def globber(s):  # noqa: F811
                return obj.strip("!") == s

        elif "!" in obj:
            raise RuntimeError("! is only supported at the start of the name.")

        elif obj.startswith("*") and obj.endswith("*") and obj != "*":

            def globber(s):
                return obj.strip("*") in s

        elif obj.startswith("*"):

            def globber(s):
                return s.endswith(obj.strip("*"))

        elif obj.endswith("*"):

            def globber(s):
                return s.startswith(obj.strip("*"))

        obj = obj.strip("*!")

    nukeables: List[Nukeable] = []

    if "a" in selectors or "r" in selectors:
        logger.info(f"gathering apps and relations ({selectors})")
        nukeables.extend(
            _get_apps_and_relations(
                model or cur_model,
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
        for model_ in get_models():
            if globber(model_):
                logger.info(f"collected {model_} for nukage")
                nukeables.append(Nukeable(model_, "model"))

    return nukeables


def print_centered(s, color: _Color = "auto"):
    console = Console(color_system=color)
    return console.print(Align(s, align="center"))


def fire(nukeable: Nukeable, nuke: str):
    """defcon 5"""
    _atom = Style(bold=True, color="green")

    nukeable_name = nukeable.name
    if not nukeable.type == "model":
        nukeable_name += f" ({nukeable.model})"

    to_nuke = Style(color=COLOR_MAP[nukeable.type])
    text = (
        Text(ICBM + " " * 2).append(nukeable_name, to_nuke).append("  " + ATOM, _atom)
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
            f"stdout={proc.stdout.read().decode('utf-8')}"
            f"stderr={proc.stderr.read().decode('utf-8')}"
        )
    else:
        logger.debug("hit and sunk")


def _nuke(
    obj: Optional[str],
    model: Optional[str] = None,
    borked: bool = False,
    selectors: Optional[str] = None,
    n: int = None,
    dry_run: bool = False,
    color: _Color = "auto",
    gently: bool = GENTLY,
):

    cur_model = model or get_current_model()
    if not cur_model:
        nukeables = []

    # user typed `jhack nuke`.
    elif obj is None and not borked and not selectors:
        logger.info("No object | selectors provided, we'll nuke the current model.")
        nukeables = [Nukeable(cur_model, "model")]

    # user typed `jhack nuke something`.
    else:
        if obj is None:
            # means we passed selectors:
            if not selectors:
                exit("invalid usage. Provide selectors or a target.")
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
            obj,
            model,
            borked=borked,
            selectors="".join(_selectors),
            cur_model=cur_model,
        )
        logger.debug(f"Gathered: {nukeables}")

    politeness = " --force --no-wait" if not gently else ""
    nukes = []
    nuked_apps = set()
    nuked_models = set()

    for nukeable in tuple(nukeables):
        logger.info(f"collecting for nukage: {nukeable}")
        if nukeable.type == "model":
            nuked_models.add(nukeable.name)
            nukes.append(
                f"juju destroy-model{politeness} --destroy-storage --no-prompt {nukeable.name}"
            )

        elif nukeable.type == "app":
            nuked_apps.add(nukeable.name)

            assert nukeable.model, f"app {nukeable.name} has unknown model"
            if nukeable.model in nuked_models:
                nukeables.remove(nukeable)
                continue

            nukes.append(
                f"juju remove-application {nukeable.name}{politeness} --no-prompt"
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
                f"Unexpected number of nukeables; expected {n}, got: {nukeables}"
            )
            for nukeable in nukeables:
                print(f"would {ATOM} {nukeable}")
            word = "less" if n > real_n else "more"
            print(f"\nThat is {word} than what you expected. Aborting...")
            return

    if not nukeables:
        print(f"Nothing to {ATOM}.")
        if not cur_model:
            print(
                f"No model currently selected. You'll have to "
                f"manually specify what you want to {ATOM}."
            )
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
            if not typer.confirm("Please confirm", default=True):
                print("Aborted.")
                return
        except typer.Abort:
            print("\nAborted.")
            return
    else:
        check_destructive_commands_allowed("nuke", "\t\n".join(nukes))

    if color == "no":
        color = None

    ascii_art = NUKE_GENTLY_ASCII_ART if gently else NUKE_ASCII_ART
    print_centered(
        Text(
            ascii_art,
            style=Style(dim=True, blink=BLINK, bold=True),
        ),
        color=color,
    )

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
            print_centered(f"{ICBM} {nkbl} still in flight", color=color)
        else:
            if not res.successful():
                print_centered(
                    f"nuke {nk!r} {ICBM} {nkbl!r} failed; someone doesn't want to die",
                    color=color,
                )

    if not dry_run:
        print_centered(Text("✞ RIP ✞", style=Style(bold=True, dim=True)), color=color)


app = typer.Typer()


@app.command()
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
        help="Exact number of things you're expectig to get nuked.Safety first.",
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
    gently: bool = typer.Option(
        False, "--gently", help="Do not --force whenever you can.", is_flag=True
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
    """
    *Surgical carpet bombing tool.*

    Attempts to guess what you want to burn, and rains holy vengeance upon it.

    Examples:

    - *nuke*: will vanquish the current model and everything in it.

    - *nuke "test-foo-&ast;"*: will bomb all nukeables starting with "test-foo-"; all models,
      applications and relations.

    - *nuke "--model foo bar-&ast;"*: will blast all nukeables starting with "bar-" in model "foo".
      As above.

    - *nuke -n=2 &ast;foo&ast;*: will blow up the two things it can find that contain the
      substring "foo"

    \n\n
    Nuke ascii art by [Bill March](https://www.asciiart.eu/weapons/explosives).
    Nuke gently ascii art by [bug](https://user.xmission.com/~emailbox/ascii_cats.htm)
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
        gently=gently,
    )
    if what is None:
        _nuke(None, **kwargs)
    else:
        for obj in what:
            _nuke(obj, **kwargs)


if __name__ == "__main__":
    _nuke("ssc:", dry_run=True)
