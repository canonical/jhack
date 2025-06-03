import sys
from typing import Dict, List, NamedTuple, TypedDict

import yaml

from jhack.helpers import fetch_file, get_units, juju_status
from jhack.logger import logger as jhack_logger

logger = jhack_logger.getChild("gather_endpoints")

AppName = Endpoint = Interface = RemoteAppName = Owner = str
RelationID = int


class AppEndpoints(TypedDict):
    requires: Dict[Endpoint, Dict[Interface, Dict[RelationID, RemoteAppName]]]
    provides: Dict[Endpoint, Dict[Interface, Dict[RelationID, RemoteAppName]]]
    peers: Dict[Endpoint, Dict[Interface, List[RelationID]]]


class PeerBinding(NamedTuple):
    provider_endpoint: str
    interface: str


class RelationBinding(NamedTuple):
    provider_model: str
    provider_endpoint: str
    interface: str
    requirer_model: str
    requirer_endpoint: str
    active: bool


def gather_endpoints(
    model=None, apps=(), include_peers: bool = False
) -> Dict[AppName, AppEndpoints]:
    status = juju_status(model=model, json=True)
    eps = {}

    for app in apps:
        if "/" in app:
            exit("use list-endpoints <APP NAME> please")

    def remotes(app, endpoint):
        if "relations" not in app:
            return []
        return app["relations"].get(endpoint, [])

    all_apps = status.get("applications")
    if not all_apps:
        sys.exit(
            f"No applications found in model {model or '<current model>'}; does the model exist?"
        )

    for app_name, app in all_apps.items():
        if apps and app_name not in apps:
            continue

        if app["application-status"]["current"] == "terminated":
            # https://bugs.launchpad.net/juju/+bug/1977582 app killed by juju/pebble, juju app
            # in terminated status.
            logger.warning(
                f"Skipping endpoint collection from application {app_name} as it is in "
                f"`terminated` state."
            )
            continue

        app_eps = {}

        is_subordinate = app.get("subordinate-to")
        if is_subordinate:
            units = get_units(app_name, model=model)
            if not units:
                logger.debug(f"skipping {app_name}: no units")
                continue
            # grab any unit. We don't do `app_name/0` because we could be on machine models.
            unit = units[0].unit_name
        else:
            units = app.get("units", None)
            if units is None:
                logger.error(
                    f"juju status for {app_name!r} has no 'units' field. "
                    f"Is the app still bootstrapping? Skipping for now..."
                )
                continue
            unit = next(iter(units))

        try:
            metadata = fetch_file(unit, "metadata.yaml", model=model)
        except RuntimeError as e:
            logger.error(
                f"Failed to fetch metadata.yaml from {unit} in "
                f"model={model or '<current model>'}\n\n"
                f"{e}\n\n"
                f"APP ={app}"
            )
            continue

        meta = yaml.safe_load(metadata)

        for role in ("requires", "provides"):
            role_eps = {
                ep: (spec["interface"], remotes(app, ep))
                for ep, spec in meta.get(role, {}).items()
            }
            app_eps[role] = role_eps

        if include_peers:
            app_eps["peers"] = [
                PeerBinding(ep, spec["interface"]) for ep, spec in meta.get("peers", {}).items()
            ]

        eps[app_name] = app_eps

    return eps


if __name__ == "__main__":
    gather_endpoints("lxd:demo")
