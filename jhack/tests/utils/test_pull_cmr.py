from unittest.mock import MagicMock, patch

import pytest

from jhack.utils.helpers.gather_endpoints import RelationBinding
from jhack.utils.integrate import _generate_pull_cmr_scripts, _find_all_possible_cmrs


def imatrix_patch(model: str):
    imatrix = MagicMock()
    imatrix.model = model

    if model == "microk8s-localhost:foo":
        imatrix._apps = [
            "traefik",
            "loki",
            "grafana",
            "prometheus",
            "catalogue",
            "alertmanager",
        ]
        imatrix._endpoints = {
            "alertmanager": {
                "requires": {
                    "ingress": (
                        "ingress",
                        [
                            {
                                "related-application": "traefik",
                                "interface": "ingress",
                                "scope": "global",
                            }
                        ],
                    ),
                    "remote-configuration": ("alertmanager_remote_configuration", []),
                    "catalogue": (
                        "catalogue",
                        [
                            {
                                "related-application": "catalogue",
                                "interface": "catalogue",
                                "scope": "global",
                            }
                        ],
                    ),
                    "certificates": ("tls-certificates", []),
                    "tracing": ("tracing", []),
                },
                "provides": {
                    "alerting": (
                        "alertmanager_dispatch",
                        [
                            {
                                "related-application": "loki",
                                "interface": "alertmanager_dispatch",
                                "scope": "global",
                            },
                            {
                                "related-application": "prometheus",
                                "interface": "alertmanager_dispatch",
                                "scope": "global",
                            },
                        ],
                    ),
                    "karma-dashboard": ("karma_dashboard", []),
                    "self-metrics-endpoint": (
                        "prometheus_scrape",
                        [
                            {
                                "related-application": "prometheus",
                                "interface": "prometheus_scrape",
                                "scope": "global",
                            }
                        ],
                    ),
                    "grafana-dashboard": (
                        "grafana_dashboard",
                        [
                            {
                                "related-application": "grafana",
                                "interface": "grafana_dashboard",
                                "scope": "global",
                            }
                        ],
                    ),
                    "grafana-source": (
                        "grafana_datasource",
                        [
                            {
                                "related-application": "grafana",
                                "interface": "grafana_datasource",
                                "scope": "global",
                            }
                        ],
                    ),
                },
            },
            "catalogue": {
                "requires": {
                    "ingress": (
                        "ingress",
                        [
                            {
                                "related-application": "traefik",
                                "interface": "ingress",
                                "scope": "global",
                            }
                        ],
                    ),
                    "certificates": ("tls-certificates", []),
                    "tracing": ("tracing", []),
                },
                "provides": {
                    "catalogue": (
                        "catalogue",
                        [
                            {
                                "related-application": "alertmanager",
                                "interface": "catalogue",
                                "scope": "global",
                            },
                            {
                                "related-application": "grafana",
                                "interface": "catalogue",
                                "scope": "global",
                            },
                            {
                                "related-application": "prometheus",
                                "interface": "catalogue",
                                "scope": "global",
                            },
                        ],
                    )
                },
            },
            "grafana": {
                "requires": {
                    "catalogue": (
                        "catalogue",
                        [
                            {
                                "related-application": "catalogue",
                                "interface": "catalogue",
                                "scope": "global",
                            }
                        ],
                    ),
                    "certificates": ("tls-certificates", []),
                    "database": ("db", []),
                    "grafana-auth": ("grafana_auth", []),
                    "grafana-dashboard": (
                        "grafana_dashboard",
                        [
                            {
                                "related-application": "alertmanager",
                                "interface": "grafana_dashboard",
                                "scope": "global",
                            },
                            {
                                "related-application": "prometheus",
                                "interface": "grafana_dashboard",
                                "scope": "global",
                            },
                        ],
                    ),
                    "grafana-source": (
                        "grafana_datasource",
                        [
                            {
                                "related-application": "alertmanager",
                                "interface": "grafana_datasource",
                                "scope": "global",
                            },
                            {
                                "related-application": "prometheus",
                                "interface": "grafana_datasource",
                                "scope": "global",
                            },
                        ],
                    ),
                    "ingress": (
                        "traefik_route",
                        [
                            {
                                "related-application": "traefik",
                                "interface": "traefik_route",
                                "scope": "global",
                            }
                        ],
                    ),
                    "oauth": ("oauth", []),
                    "receive-ca-cert": ("certificate_transfer", []),
                    "tracing": ("tracing", []),
                },
                "provides": {
                    "metrics-endpoint": (
                        "prometheus_scrape",
                        [
                            {
                                "related-application": "prometheus",
                                "interface": "prometheus_scrape",
                                "scope": "global",
                            }
                        ],
                    )
                },
            },
            "loki": {
                "requires": {
                    "alertmanager": (
                        "alertmanager_dispatch",
                        [
                            {
                                "related-application": "alertmanager",
                                "interface": "alertmanager_dispatch",
                                "scope": "global",
                            }
                        ],
                    ),
                    "ingress": (
                        "ingress_per_unit",
                        [
                            {
                                "related-application": "traefik",
                                "interface": "ingress_per_unit",
                                "scope": "global",
                            }
                        ],
                    ),
                    "certificates": ("tls-certificates", []),
                    "catalogue": ("catalogue", []),
                    "tracing": ("tracing", []),
                },
                "provides": {
                    "logging": ("loki_push_api", []),
                    "grafana-source": ("grafana_datasource", []),
                    "metrics-endpoint": (
                        "prometheus_scrape",
                        [
                            {
                                "related-application": "prometheus",
                                "interface": "prometheus_scrape",
                                "scope": "global",
                            }
                        ],
                    ),
                    "grafana-dashboard": ("grafana_dashboard", []),
                },
            },
            "prometheus": {
                "requires": {
                    "metrics-endpoint": (
                        "prometheus_scrape",
                        [
                            {
                                "related-application": "alertmanager",
                                "interface": "prometheus_scrape",
                                "scope": "global",
                            },
                            {
                                "related-application": "grafana",
                                "interface": "prometheus_scrape",
                                "scope": "global",
                            },
                            {
                                "related-application": "loki",
                                "interface": "prometheus_scrape",
                                "scope": "global",
                            },
                            {
                                "related-application": "traefik",
                                "interface": "prometheus_scrape",
                                "scope": "global",
                            },
                        ],
                    ),
                    "alertmanager": (
                        "alertmanager_dispatch",
                        [
                            {
                                "related-application": "alertmanager",
                                "interface": "alertmanager_dispatch",
                                "scope": "global",
                            }
                        ],
                    ),
                    "ingress": (
                        "ingress_per_unit",
                        [
                            {
                                "related-application": "traefik",
                                "interface": "ingress_per_unit",
                                "scope": "global",
                            }
                        ],
                    ),
                    "catalogue": (
                        "catalogue",
                        [
                            {
                                "related-application": "catalogue",
                                "interface": "catalogue",
                                "scope": "global",
                            }
                        ],
                    ),
                    "certificates": ("tls-certificates", []),
                    "tracing": ("tracing", []),
                },
                "provides": {
                    "self-metrics-endpoint": ("prometheus_scrape", []),
                    "grafana-source": (
                        "grafana_datasource",
                        [
                            {
                                "related-application": "grafana",
                                "interface": "grafana_datasource",
                                "scope": "global",
                            }
                        ],
                    ),
                    "grafana-dashboard": (
                        "grafana_dashboard",
                        [
                            {
                                "related-application": "grafana",
                                "interface": "grafana_dashboard",
                                "scope": "global",
                            }
                        ],
                    ),
                    "receive-remote-write": ("prometheus_remote_write", []),
                },
            },
            "traefik": {
                "requires": {
                    "certificates": ("tls-certificates", []),
                    "experimental-forward-auth": ("forward_auth", []),
                    "logging": ("loki_push_api", []),
                    "tracing": ("tracing", []),
                    "receive-ca-cert": ("certificate_transfer", []),
                },
                "provides": {
                    "ingress": (
                        "ingress",
                        [
                            {
                                "related-application": "alertmanager",
                                "interface": "ingress",
                                "scope": "global",
                            },
                            {
                                "related-application": "catalogue",
                                "interface": "ingress",
                                "scope": "global",
                            },
                        ],
                    ),
                    "ingress-per-unit": (
                        "ingress_per_unit",
                        [
                            {
                                "related-application": "loki",
                                "interface": "ingress_per_unit",
                                "scope": "global",
                            },
                            {
                                "related-application": "prometheus",
                                "interface": "ingress_per_unit",
                                "scope": "global",
                            },
                        ],
                    ),
                    "metrics-endpoint": (
                        "prometheus_scrape",
                        [
                            {
                                "related-application": "prometheus",
                                "interface": "prometheus_scrape",
                                "scope": "global",
                            }
                        ],
                    ),
                    "traefik-route": (
                        "traefik_route",
                        [
                            {
                                "related-application": "grafana",
                                "interface": "traefik_route",
                                "scope": "global",
                            }
                        ],
                    ),
                    "grafana-dashboard": ("grafana_dashboard", []),
                },
            },
        }

    if model == "microk8s-localhost:bar":
        imatrix._apps = ["tempo"]
        imatrix._endpoints = {
            "tempo": {
                "requires": {
                    "certificates": ("tls-certificates", []),
                    "ingress": ("traefik_route", []),
                    "logging": ("loki_push_api", []),
                    "s3": ("s3", []),
                },
                "provides": {
                    "grafana-dashboard": ("grafana_dashboard", []),
                    "grafana-source": ("grafana_datasource", []),
                    "metrics-endpoint": ("prometheus_scrape", []),
                    "tracing": ("tracing", []),
                },
            }
        }
    return imatrix


def test_find_possible_cmrs():
    with patch("jhack.utils.integrate.IntegrationMatrix", new=imatrix_patch):
        opts = _find_all_possible_cmrs(
            "microk8s-localhost:bar", "microk8s-localhost:foo"
        )

    assert opts == {
        "0.0": (
            "loki",
            RelationBinding(
                provider_model="microk8s-localhost:foo",
                provider_endpoint="logging",
                interface="loki_push_api",
                requirer_model="microk8s-localhost:bar",
                requirer_endpoint="logging",
                active=False,
            ),
            "tempo",
            True,
        ),
        "1.0": (
            "tempo",
            RelationBinding(
                provider_model="microk8s-localhost:bar",
                provider_endpoint="tracing",
                interface="tracing",
                requirer_model="microk8s-localhost:foo",
                requirer_endpoint="tracing",
                active=False,
            ),
            "alertmanager",
            False,
        ),
        "2.0": (
            "tempo",
            RelationBinding(
                provider_model="microk8s-localhost:bar",
                provider_endpoint="tracing",
                interface="tracing",
                requirer_model="microk8s-localhost:foo",
                requirer_endpoint="tracing",
                active=False,
            ),
            "catalogue",
            False,
        ),
        "3.0": (
            "tempo",
            RelationBinding(
                provider_model="microk8s-localhost:bar",
                provider_endpoint="grafana-dashboard",
                interface="grafana_dashboard",
                requirer_model="microk8s-localhost:foo",
                requirer_endpoint="grafana-dashboard",
                active=False,
            ),
            "grafana",
            False,
        ),
        "3.1": (
            "tempo",
            RelationBinding(
                provider_model="microk8s-localhost:bar",
                provider_endpoint="grafana-source",
                interface="grafana_datasource",
                requirer_model="microk8s-localhost:foo",
                requirer_endpoint="grafana-source",
                active=False,
            ),
            "grafana",
            False,
        ),
        "3.2": (
            "tempo",
            RelationBinding(
                provider_model="microk8s-localhost:bar",
                provider_endpoint="tracing",
                interface="tracing",
                requirer_model="microk8s-localhost:foo",
                requirer_endpoint="tracing",
                active=False,
            ),
            "grafana",
            False,
        ),
        "4.0": (
            "tempo",
            RelationBinding(
                provider_model="microk8s-localhost:bar",
                provider_endpoint="tracing",
                interface="tracing",
                requirer_model="microk8s-localhost:foo",
                requirer_endpoint="tracing",
                active=False,
            ),
            "loki",
            False,
        ),
        "5.0": (
            "tempo",
            RelationBinding(
                provider_model="microk8s-localhost:bar",
                provider_endpoint="metrics-endpoint",
                interface="prometheus_scrape",
                requirer_model="microk8s-localhost:foo",
                requirer_endpoint="metrics-endpoint",
                active=False,
            ),
            "prometheus",
            False,
        ),
        "5.1": (
            "tempo",
            RelationBinding(
                provider_model="microk8s-localhost:bar",
                provider_endpoint="tracing",
                interface="tracing",
                requirer_model="microk8s-localhost:foo",
                requirer_endpoint="tracing",
                active=False,
            ),
            "prometheus",
            False,
        ),
        "6.0": (
            "tempo",
            RelationBinding(
                provider_model="microk8s-localhost:bar",
                provider_endpoint="tracing",
                interface="tracing",
                requirer_model="microk8s-localhost:foo",
                requirer_endpoint="tracing",
                active=False,
            ),
            "traefik",
            False,
        ),
        "7.0": (
            "traefik",
            RelationBinding(
                provider_model="microk8s-localhost:foo",
                provider_endpoint="traefik-route",
                interface="traefik_route",
                requirer_model="microk8s-localhost:bar",
                requirer_endpoint="ingress",
                active=False,
            ),
            "tempo",
            True,
        ),
    }


def test_pull_cmr():
    setup, relate = _generate_pull_cmr_scripts(
        [
            (
                "loki",
                RelationBinding(
                    provider_model="microk8s-localhost:foo",
                    provider_endpoint="logging",
                    interface="loki_push_api",
                    requirer_model="microk8s-localhost:bar",
                    requirer_endpoint="logging",
                    active=False,
                ),
                "tempo",
                True,
            )
        ]
    )

    assert setup == [
        "juju offer -c microk8s-localhost bar.tempo:logging",
        "juju consume -m microk8s-localhost:foo microk8s-localhost:admin/bar.tempo",
    ]

    assert relate == [
        "juju relate -m microk8s-localhost:foo tempo:logging loki:logging"
    ]


def test_push_cmr():
    setup, relate = _generate_pull_cmr_scripts(
        [
            (
                "tempo",
                RelationBinding(
                    provider_model="microk8s-localhost:bar",
                    provider_endpoint="tracing",
                    interface="tracing",
                    requirer_model="microk8s-localhost:foo",
                    requirer_endpoint="tracing",
                    active=False,
                ),
                "loki",
                False,
            )
        ]
    )

    assert setup == [
        "juju offer -c microk8s-localhost foo.loki:tracing",
        "juju consume -m microk8s-localhost:bar microk8s-localhost:admin/foo.loki",
    ]
    assert relate == [
        "juju relate -m microk8s-localhost:bar loki:tracing tempo:tracing"
    ]


def test_pull_cmr_different_endpoint():
    setup, relate = _generate_pull_cmr_scripts(
        [
            (
                "traefik",
                RelationBinding(
                    provider_model="microk8s-localhost:foo",
                    provider_endpoint="traefik-route",
                    interface="traefik_route",
                    requirer_model="microk8s-localhost:bar",
                    requirer_endpoint="ingress",
                    active=False,
                ),
                "tempo",
                True,
            )
        ]
    )

    assert setup == [
        "juju offer -c microk8s-localhost foo.traefik:traefik-route",
        "juju consume -m microk8s-localhost:bar microk8s-localhost:admin/foo.traefik",
    ]

    assert relate == [
        "juju relate -m microk8s-localhost:bar traefik:traefik-route tempo:ingress"
    ]
