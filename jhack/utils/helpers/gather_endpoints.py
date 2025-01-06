import itertools
import sys
from dataclasses import dataclass
from typing import Dict, List, NamedTuple, Union, Optional

from jhack.helpers import (
    juju_status,
    get_relations,
    RelationType,
    get_app_metadata,
)
from jhack.logger import logger as jhack_logger

logger = jhack_logger.getChild("gather_endpoints")

AppName = Endpoint = Interface = RemoteAppName = Owner = str
RelationID = int


@dataclass
class AppEndpoints:
    app: str
    model: Optional[str]
    requires: List[Union["RelationEndpoint", "RelationBinding"]]
    provides: List[Union["RelationEndpoint", "RelationBinding"]]
    peers: List["PeerBinding"]
    cmrs: List["RelationBinding"]


class PeerBinding(NamedTuple):
    app: str
    model: str
    endpoint: str
    interface: str

    @property
    def requirer_app(self):
        return self.app

    @property
    def provider_app(self):
        return self.app

    @property
    def provider_endpoint(self):
        return self.endpoint

    @property
    def requirer_endpoint(self):
        return self.endpoint

    @property
    def provider_model(self):
        return self.model

    @property
    def requirer_model(self):
        return self.model


class RelationBinding(NamedTuple):
    provider_app: str
    provider_model: str
    provider_endpoint: str
    interface: str
    requirer_app: str
    requirer_model: str
    requirer_endpoint: str
    active: bool = True

    def other_app(self, app: str):
        if app == self.provider_app:
            return self.requirer_app
        return self.provider_app

    def other_endpoint(self, endpoint: str):
        if endpoint == self.provider_endpoint:
            return self.requirer_endpoint
        return self.provider_endpoint

    def other_model(self, model: str):
        if model == self.provider_model:
            return self.requirer_model
        return self.provider_model

    @property
    def is_cmr(self):
        return self.provider_model != self.requirer_model


class RelationEndpoint(NamedTuple):
    app: str
    model: str
    endpoint: str
    interface: str

    def bound_as_provider(
        self, other: "RelationEndpoint", active: bool = False
    ) -> RelationBinding:
        """Create a relation binding between these two endpoints, where this one is provider."""
        return RelationBinding(
            provider_app=self.app,
            provider_model=self.model,
            provider_endpoint=self.endpoint,
            requirer_app=other.app,
            requirer_model=other.model,
            requirer_endpoint=other.endpoint,
            interface=self.interface,
            active=active,
        )


def gather_endpoints(
    model=None,
    apps=(),
    include_peers: bool = False,
    include_cmrs: bool = False,
    include_inactive: bool = True,
) -> Dict[AppName, AppEndpoints]:
    for app in apps:
        if "/" in app:
            raise ValueError(f"not an app: {app}")

    eps = {}

    status = juju_status(model=model, json=True)
    all_relations = get_relations(model)

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

        CMR_endpoints = status.get("application-endpoints", ())

        def is_cross_model(obj: str):
            return obj in CMR_endpoints

        app_eps = {
            "cmrs": [],
            "peers": [
                PeerBinding(
                    app=r.provider,
                    model=model,
                    endpoint=r.provider_endpoint,
                    interface=r.interface,
                )
                for r in all_relations
                if r.provider == app_name and r.type is RelationType.peer
            ]
            if include_peers
            else [],
            "requires": [
                RelationBinding(
                    provider_app=r.provider,
                    provider_model=model,
                    provider_endpoint=r.provider_endpoint,
                    interface=r.interface,
                    requirer_app=r.requirer,
                    requirer_model=model,
                    requirer_endpoint=r.requirer_endpoint,
                )
                for r in all_relations
                if r.requirer == app_name
                and r.type in {RelationType.regular, RelationType.subordinate}
                and r.provider in all_apps
            ],
            "provides": [
                RelationBinding(
                    provider_app=r.provider,
                    provider_model=model,
                    provider_endpoint=r.provider_endpoint,
                    interface=r.interface,
                    requirer_app=r.requirer,
                    requirer_model=model,
                    requirer_endpoint=r.requirer_endpoint,
                )
                for r in all_relations
                if r.provider == app_name
                and r.type in {RelationType.regular, RelationType.subordinate}
                and r.requirer in all_apps
            ],
        }

        if include_inactive:
            # TODO: replace RelationEndpoint with RelationBinding here

            active_endpoints = {
                binding.provider_endpoint for binding in app_eps["provides"]
            }.union({binding.requirer_endpoint for binding in app_eps["requires"]})

            meta = get_app_metadata(app_name, app_meta=app, model=model)

            for ep, spec in meta.get("provides", {}).items():
                if ep in active_endpoints:
                    continue
                app_eps["provides"].append(
                    RelationEndpoint(
                        app=app_name,
                        model=model,
                        endpoint=ep,
                        interface=spec["interface"],
                    )
                )

            for ep, spec in meta.get("requires", {}).items():
                if ep in active_endpoints:
                    continue
                app_eps["requires"].append(
                    RelationEndpoint(
                        app=app_name,
                        model=model,
                        endpoint=ep,
                        interface=spec["interface"],
                    )
                )

        if include_cmrs:
            for rel in all_relations:
                # "application-endpoints": {
                #   "tempo": {
                #     "url": "mk8s:admin/svcgraph.tempo",
                #     "endpoints": {
                #       "tracing": {
                #         "interface": "tracing",
                #         "role": "provider"
                #       }
                #     },
                #     "application-status": {
                #       "current": "active",
                #       "message": "Degraded.",
                #       "since": "05 Dec 2024 11:05:17+01:00"
                #     },
                #     "relations": {
                #       "tracing": [
                #         "istio-ingress-k8s"
                #       ]
                #     }
                if is_cross_model(rel.requirer):
                    # parse "mk8s:admin/svcgraph.tempo"
                    requirer_model = CMR_endpoints[rel.requirer]["url"].split(".")[0]
                    provider_model = f"{status['model']['controller']}:admin/{status['model']['name']}"
                elif is_cross_model(rel.provider):
                    requirer_model = f"{status['model']['controller']}:admin/{status['model']['name']}"
                    provider_model = CMR_endpoints[rel.provider]["url"].split(".")[0]
                else:
                    continue  # not a CMR
                cmr = RelationBinding(
                    provider_app=rel.provider,
                    provider_model=provider_model,
                    provider_endpoint=rel.provider_endpoint,
                    interface=rel.interface,
                    requirer_app=rel.requirer,
                    requirer_model=requirer_model,
                    requirer_endpoint=rel.requirer_endpoint,
                )
                app_eps["cmrs"].append(cmr)

        eps[app_name] = AppEndpoints(app=app_name, model=model, **app_eps)
    return eps


def build_matrix(
    endpoints: Dict[AppName, AppEndpoints],
    include_peers: bool = False,
    include_inactive: bool = True,
) -> List[List[List[Union[PeerBinding, RelationBinding, RelationEndpoint]]]]:
    apps = list(endpoints)
    mtrx = [[[] for _ in range(len(apps))] for _ in range(len(apps))]

    for provider, requirer in itertools.product(apps, repeat=2):
        prov_idx = apps.index(provider)
        req_idx = apps.index(requirer)

        if provider == requirer:
            if include_peers:
                mtrx[prov_idx][req_idx] = endpoints[provider].peers  # PeerBinding
            continue

        provides = endpoints[provider].provides
        requires = endpoints[requirer].requires
        interfaces_supported_by_requirer = set(r.interface for r in requires)

        shared: List[RelationBinding] = [
            binding
            for binding in provides
            if binding.interface in interfaces_supported_by_requirer
            and isinstance(binding, RelationBinding)
            and binding.provider_app == provider
            and binding.requirer_app == requirer
        ]
        if include_inactive:
            # FIXME: replace this with a not RelationBinding.active check
            shared.extend(
                binding
                for binding in provides
                if binding.interface in interfaces_supported_by_requirer
                and isinstance(binding, RelationEndpoint)
            )

        # sort by interface name first, provider endpoint, requirer endpoint.
        sorted_s = sorted(
            shared,
            key=lambda foo: (
                foo.interface,
                getattr(foo, "requirer_endpoint")
                if hasattr(foo, "requirer_endpoint")
                else foo.endpoint,
                # foo.requirer_endpoint,
            ),
        )

        mtrx[prov_idx][req_idx].extend(sorted_s)
    return mtrx


if __name__ == "__main__":
    eps = gather_endpoints("test-nginxc", include_peers=True, include_inactive=True)
    mtrx = build_matrix(endpoints=eps)
    print(eps)
