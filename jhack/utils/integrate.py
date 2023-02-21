import itertools
import re
import sys
import time
from collections import defaultdict
from functools import partial
from typing import Dict, List, Optional, TypedDict, NamedTuple, Union, Tuple

import typer
import yaml
from rich.align import Align
from rich.color import Color
from rich.console import Console
from rich.live import Live
from rich.prompt import Prompt
from rich.style import Style
from rich.table import Table
from rich.text import Text

from jhack.helpers import (
    ColorOption,
    JPopen,
    RichSupportedColorOptions,
    fetch_file,
    juju_status,
)
from jhack.logger import logger as jhack_logger

AppName = Endpoint = Interface = RemoteAppName = str
RelationID = int
logger = jhack_logger.getChild("integrate")


class _AppEndpoints(TypedDict):
    requires: Dict[Endpoint, Dict[Interface, Dict[RelationID, RemoteAppName]]]
    provides: Dict[Endpoint, Dict[Interface, Dict[RelationID, RemoteAppName]]]
    peers: Dict[Endpoint, Dict[Interface, List[RelationID]]]


class PeerBinding(NamedTuple):
    endpoint: str
    interface: str


class RelationBinding(NamedTuple):
    provider_endpoint: str
    interface: str
    requirer_endpoint: str
    active: bool


def _gather_endpoints(model=None, apps=(), include_peers: bool = False) -> Dict[AppName, _AppEndpoints]:
    status = juju_status(model=model, json=True)
    eps = {}

    def remotes(app, endpoint):
        if "relations" not in app:
            return []
        return app["relations"].get(endpoint, [])

    all_apps = status.get("applications")
    if not all_apps:
        sys.exit(f"No applications found in model {model}; does the model exist?")

    for app_name, app in all_apps.items():
        if apps and app_name not in apps:
            continue

        app_eps = {}
        unit = next(iter(app["units"]))
        metadata = fetch_file(unit, "metadata.yaml", model=model)
        meta = yaml.safe_load(metadata)

        for role in ("requires", "provides"):
            role_eps = {
                ep: (spec["interface"], remotes(app, ep))
                for ep, spec in meta.get(role, {}).items()
            }
            app_eps[role] = role_eps

        if include_peers:
            app_eps["peers"] = [PeerBinding(ep, spec["interface"]) for ep, spec in meta.get("peers", {}).items()]

        eps[app_name] = app_eps

    return eps


class IntegrationMatrix:
    cell_border_style = Style()
    peer_cell_border_style = Style(color=Color.from_rgb(150, 30, 30))
    no_interfaces_text_style = Style(color=Color.from_rgb(180, 150, 30))

    na_text_style = Style(color=Color.from_rgb(180, 100, 170))

    peer_cell_text_style = Style(color=Color.from_rgb(180, 200, 100))
    active_cell_text_style = Style(color=Color.from_rgb(10, 250, 80))
    inactive_cell_text_style = Style(color=Color.from_rgb(250, 0, 0))

    def __init__(
            self,
            apps: str = None,
            model: str = None,
            include_peers: bool = False,
            color: RichSupportedColorOptions = "auto",
    ):
        self._model = model
        self._color = color
        self._endpoints = _gather_endpoints(model, apps, include_peers=include_peers)
        self._apps = tuple(sorted(self._endpoints))
        self._include_peers = include_peers

        if apps:
            apps_re = re.compile(apps)
            self._apps = tuple(filter(lambda x: apps_re.match(x), self._apps))

        # X axis: requires
        # Y axis: provides
        self.matrix: List[List[Union[List[PeerBinding], List[RelationBinding]]]] = self._build_matrix()

    def refresh(self):
        self._endpoints = _gather_endpoints(model=self._model, apps=self._apps)

    def _pairs(self):
        # returns provider, requirer pairs.
        return itertools.product(self._apps, repeat=2)

    def _cells(self, skip_diagonal=True, yield_indices=False):
        for i, row in enumerate(self.matrix):
            for j, cell in enumerate(row):
                if skip_diagonal and i == j:
                    continue
                if yield_indices:
                    yield (i, j), cell
                else:
                    yield cell

    def _build_matrix(self) -> List[List[Union[List[PeerBinding], List[RelationBinding]]]]:
        apps = self._apps
        mtrx = [[[] for _ in range(len(apps))] for _ in range(len(apps))]

        for provider, requirer in self._pairs():
            prov_idx = apps.index(provider)
            req_idx = apps.index(requirer)

            if provider == requirer:
                if self._include_peers:
                    mtrx[prov_idx][req_idx] = self._endpoints[provider].get("peers")  # PeerBinding
                continue

            provides = self._endpoints[provider]["provides"]
            requires = self._endpoints[requirer]["requires"]

            # mapping from each supported interface to the endpoints using that interface, for the requirer.
            requirer_interfaces_to_endpoints = defaultdict(list)
            for endpoint, (interface, connected_providers) in requires.items():
                requirer_interfaces_to_endpoints[interface].append((endpoint, connected_providers))

            shared: List[RelationBinding] = []

            for provider_endpoint, (interface, connected_requirers) in provides.items():
                requirer_endpoints_for_interface = requirer_interfaces_to_endpoints[interface]
                for requirer_endpoint, connected_providers in requirer_endpoints_for_interface:
                    active = ((requirer in connected_requirers) and
                              (provider in connected_providers))
                    shared.append(
                        RelationBinding(provider_endpoint, interface, requirer_endpoint, active)
                    )

            # sort by interface name first, provider endpoint, requirer endpoint, status then.
            shared = sorted(shared, key=lambda foo: (foo[1], foo[0], foo[2], foo[3]))

            mtrx[prov_idx][req_idx].extend(shared)
        return mtrx

    def _render_cell(self, provider_idx: int, requirer_idx: int):
        # this is our cell
        bindings: Union[List[PeerBinding], List[RelationBinding]] = self.matrix[provider_idx][requirer_idx]
        peer = provider_idx == requirer_idx

        t = Table(show_header=False, expand=True,
                  border_style=self.peer_cell_border_style if peer else self.cell_border_style)
        t.add_column("")

        if peer:
            bindings: List[PeerBinding]

            if not self._include_peers:
                return Text("-n/a-", style=self.na_text_style)

            if not bindings:
                t.add_row(Text("- no interfaces - ", style=self.no_interfaces_text_style))
                return t

            for endpoint, interface in bindings:
                sym = "↻"
                fmt_obj = f"{endpoint} [{interface}] {sym}"
                t.add_row(Text(fmt_obj, style=self.peer_cell_text_style))
            return t

        else:
            bindings: List[RelationBinding]

            if not bindings:
                t.add_row(Text("- no interfaces - ", style=self.no_interfaces_text_style))
                return t

            for provider_endpoint, interface, requirer_endpoint, active in bindings:
                if active:
                    symtail, symhead = ">-", "->"
                    color = self.active_cell_text_style
                else:
                    symtail, symhead = "X-", "-X"
                    color = self.inactive_cell_text_style

                fmt_obj = f"{provider_endpoint} {symtail}[{interface}]{symhead} {requirer_endpoint}"
                t.add_row(Text(fmt_obj, style=color))
            return t

    def render(self, refresh: bool = False):
        if refresh:
            self.refresh()
        table = Table(title="integration  v0.1", expand=True)
        table.add_column(r"providers\requirers")

        for app in self._apps:
            table.add_column(app)

        apps = self._apps

        rendered_matrix = [
            [
                self._render_cell(provider_idx=prov_idx, requirer_idx=req_idx)
                for req_idx in range(len(apps))
            ]
            for prov_idx in range(len(apps))
        ]

        for app, row in zip(apps, rendered_matrix):
            table.add_row(app, *row)
        return Align.center(table)

    def pprint(self):
        c = Console(color_system=self._color)
        c.print(self.render())

    def watch(self, refresh_rate=0.2):
        rrate = refresh_rate or 0.2
        live = Live(
            get_renderable=partial(self.render, refresh=True), refresh_per_second=rrate
        )
        live.start()

        try:
            while True:
                time.sleep(rrate)
                live.refresh()

        except KeyboardInterrupt:
            print("aborting...")

        live.stop()
        live.console.clear_live()
        del live

    def _get_endpoint(self, app_name, role, interface):
        # get endpoint from interface name
        bindings = self._endpoints[app_name][role]
        for ep, (intf, _) in bindings.items():
            if intf == interface:
                return ep
        raise ValueError(f"cannot find binding for {interface} in {app_name}: {role}")

    def _get_interface(self, app_name, role, endpoint):
        # get interface name from endpoint
        try:
            return self._endpoints[app_name][role][endpoint][0]
        except KeyError as e:
            raise ValueError(
                f"cannot find interface for {endpoint} in {app_name}: {role}"
            ) from e

    def _apply_to_all(
            self,
            include: str,
            exclude: str,
            verb: str,
            juju_cmd: str,
            dry_run: bool = False,
            active: bool = None,
    ):
        targets = self._apps

        if include:
            inc_f = re.compile(include)
            targets = filter(lambda x: inc_f.match(x), targets)

        if exclude:
            exc_f = re.compile(exclude)
            targets = filter(lambda x: not exc_f.match(x), targets)

        target_apps = set(targets)
        logger.debug(f"target applications: {target_apps}")

        target_bindings = []

        for (prov_idx, req_idx), bindings in self._cells(skip_diagonal=True, yield_indices=True):
            for (provider_endpoint, interface, requirer_endpoint, is_active) in bindings:
                prov = self._apps[prov_idx]
                req = self._apps[req_idx]

                if active in {True, False}:
                    # only include if the interface is currently not at the desired state
                    if is_active is not active:
                        logger.debug(
                            f"skipping {prov}:{provider_endpoint} --> [{interface}] --> {req}:{requirer_endpoint} "
                            f'interface is already {"in" if active else ""}active'
                        )
                        continue

                if prov not in target_apps:
                    logger.debug(f"skipping {prov}: not a target")
                    continue

                target_bindings.append((f"{prov}:{provider_endpoint}",
                                        interface,
                                        f"{req}:{requirer_endpoint}"))

        logger.debug(f"target interfaces: {target_bindings}")

        if not target_bindings:
            print(f"Nothing to {verb}.")
            return

        if dry_run:
            print(f"would {verb}: {target_apps}")

        cmd_list: List[str] = []
        for ep1, interface, ep2 in target_bindings:
            sym = "X" if verb == 'disconnect' else '-->'
            cmd = f"{juju_cmd} {ep1} {sym} [{interface}] {sym}  {ep2}"
            cmd_list.append(cmd)
            if dry_run:
                print(cmd.replace(juju_cmd, verb))

        if dry_run:
            return

        print(f"{verb.title()}ing relations...")
        for cmd, (ep1, _, ep2) in zip(cmd_list, target_bindings):
            print(f"\t{ep1} <--> {ep2}")
            JPopen(cmd.split(), wait=True)

        print("Done.")

    def connect(self, include: str = None, exclude: str = None, dry_run: bool = False):
        self._apply_to_all(
            include,
            exclude,
            verb="connect",
            juju_cmd="relate",
            dry_run=dry_run,
            active=False,
        )

    def disconnect(
            self, include: str = None, exclude: str = None, dry_run: bool = False
    ):
        self._apply_to_all(
            include,
            exclude,
            verb="disconnect",
            juju_cmd="remove-relation",
            dry_run=dry_run,
            active=True,
        )


# API
def link(
        include: str = typer.Option(
            None,
            "--include",
            "-i",
            help="Regex a provider will have to match to be included in the target pool",
        ),
        exclude: str = typer.Option(
            None,
            "--exclude",
            "-e",
            help="Regex a provider will have to NOT match to be included in the target pool",
        ),
        dry_run: bool = False,
        model: str = typer.Option(
            None, "--model", "-m", help="Model in which to apply this command."
        ),
):
    """Cross-relate applications in all possible ways."""
    IntegrationMatrix(model=model).connect(
        include=include, exclude=exclude, dry_run=dry_run
    )


def clear(
        include: str = typer.Option(
            None,
            "--include",
            "-i",
            help="Regex an application will have to match to be included in the target pool",
        ),
        exclude: str = typer.Option(
            None,
            "--exclude",
            "-e",
            help="Regex an application will have to NOT match to be included in the target pool",
        ),
        dry_run: bool = False,
        model: str = typer.Option(
            None, "--model", "-m", help="Model in which to apply this command."
        ),
):
    """Blanket-nuke relations between applications."""
    IntegrationMatrix(model=model).disconnect(
        include=include, exclude=exclude, dry_run=dry_run
    )


def show(
        apps: str = typer.Argument(
            None, help="Regex to filter the applications to include in the listing."
        ),
        watch: bool = typer.Option(
            None, "--watch", "-w", help="Keep this alive and refresh"
        ),
        refresh_rate: float = typer.Option(
            None, "--refresh-rate", "-r", help="Refresh rate for watch."
        ),
        model: str = typer.Option(
            None, "--model", "-m", help="Model in which to apply this command."
        ),
        show_peers: bool = typer.Option(
            None, "--show-peers", "-p", help="Include peer relations in the matrix.", is_flag=True
        ),
        color: Optional[str] = ColorOption,
):
    """Display the avaiable integrations between any number of juju applications in a nice matrix."""
    mtrx = IntegrationMatrix(apps=apps, model=model, color=color, include_peers=show_peers)
    if watch:
        mtrx.watch(refresh_rate=refresh_rate)
    else:
        mtrx.pprint()


def cmr(remote, local=None, dry_run: bool = False):
    """Command to pull a CMR over from some other model to the current one.

    Usage: jhack pull-cmr some-model

    A prompt will show, requesting you to pick which relation to create.
    Select one and you should be good to go! Enjoy.
    """
    return _cmr(remote, local=local, dry_run=dry_run)


def _cmr(remote, local=None, dry_run: bool = False):
    mtrx1 = IntegrationMatrix(model=local)
    mtrx2 = IntegrationMatrix(model=remote)
    apps1 = mtrx1._apps
    apps2 = mtrx2._apps

    cmrs: Dict[Tuple[AppName, AppName], List[RelationBinding]] = {}

    for provider, requirer in itertools.product(apps1, apps2):
        provides = mtrx1._endpoints[provider]["provides"]
        requires = mtrx2._endpoints[requirer]["requires"]

        # mapping from each supported interface to the endpoints using that interface, for the requirer.
        requirer_interfaces_to_endpoints = defaultdict(list)
        for endpoint, (interface, connected_providers) in requires.items():
            requirer_interfaces_to_endpoints[interface].append((endpoint, connected_providers))

        shared: List[RelationBinding] = []

        for provider_endpoint, (interface, connected_requirers) in provides.items():
            requirer_endpoints_for_interface = requirer_interfaces_to_endpoints[interface]
            for requirer_endpoint, connected_providers in requirer_endpoints_for_interface:
                active = ((requirer in connected_requirers) and
                          (provider in connected_providers))
                shared.append(
                    RelationBinding(provider_endpoint, interface, requirer_endpoint, active)
                )

        if shared:
            cmrs[(provider, requirer)] = shared

    opts = {}
    for i, ((prov, req), bindings) in enumerate(cmrs.items()):
        binding: RelationBinding
        for j, binding in enumerate(bindings):
            print(
                f"({i}.{j}) := \t {prov}:{binding.provider_endpoint} --> [{binding.interface}] --> {req}:{binding.requirer_endpoint} ")
            opts[f"{i}.{j}"] = (prov, binding, req)

    cmr = Prompt.ask("Pick a CMR", choices=list(opts), default=list(opts)[0])

    prov, binding, req = opts[cmr]

    def fmt_endpoint(model, app, endpoint):
        return (
                Text(model or "<this model>", style="red")
                + "."
                + Text(app, style="purple")
                + ":"
                + Text(endpoint, style="cyan")
        )

    c = Console()
    txt = (
            Text("Pulling ")
            + fmt_endpoint(remote, req, binding.requirer_endpoint)
            + " --> ["
            + Text(binding.interface, style="green")
            + "] --> "
            + fmt_endpoint(local, prov, binding.provider_endpoint)
    )
    c.print(txt)

    script = [
        f"juju offer {remote}.{req}:{binding.requirer_endpoint}",
        f"juju consume admin/{remote}.{req}",
        f"juju relate {req}:{binding.requirer_endpoint} {prov}:{binding.provider_endpoint}",
    ]

    if dry_run:
        print("would run:", "\n\t".join(script))
        return

    for cmd in script:
        if JPopen(cmd.split()).wait() != 0:
            print(f"{cmd} failed. Aborting...")
            return


if __name__ == "__main__":
    mtrx = IntegrationMatrix(include_peers=True)
    mtrx.disconnect()
    # mtrx.watch()
    # mtrx.pprint()
    mtrx.pprint()
