import pytest

from jhack.utils.show_relation import (
    Relation,
    RelationEndpointURL,
    RelationType,
    _match_endpoint,
)


@pytest.mark.parametrize(
    "unit, endpoint1, endpoint2",
    (
        (None, None, None),
        (0, None, None),
        (0, "lokiep", None),
        (0, None, "promep"),
        (0, "lokiep", "promep"),
        (None, "lokiep", "promep"),
    ),
)
@pytest.mark.parametrize(
    "rel, ep1, ep2, match, flip",
    (
        (
            Relation("loki", "lokiep", "prom", "promep", "_", RelationType.regular),
            "loki",
            "prom",
            True,
            False,
        ),
        (
            Relation("prom", "promep", "loki", "lokiep", "_", RelationType.regular),
            "loki",
            "prom",
            True,
            True,
        ),
    ),
)
def test_match_endpoint(rel, ep1, ep2, match, flip, unit, endpoint1, endpoint2):
    if unit is not None:
        ep1 = ep1 + f"/{unit}"
    if endpoint1:
        ep1 = ep1 + f":{endpoint1}"
    if endpoint2:
        ep2 = ep2 + f":{endpoint2}"

    rep1 = RelationEndpointURL(ep1)
    rep2 = RelationEndpointURL(ep2)
    assert _match_endpoint(rel, rep1, rep2) == (match, flip)


@pytest.mark.parametrize(
    "unit, endpoint1, endpoint2",
    (
        (None, None, None),
        (0, None, None),
        (0, "promep", None),
        (0, None, "promep"),
        (0, "promep", "promep"),
        (None, "promep", "promep"),
    ),
)
@pytest.mark.parametrize(
    "rel, ep1, ep2, match, flip",
    (
        (
            Relation("prom", "promep", "prom", "promep", "_", RelationType.peer),
            "prom",
            "prom",
            True,
            False,
        ),
        (
            Relation("prom", "promep", "prom", "promep", "_", RelationType.peer),
            "prom",
            None,
            True,
            False,
        ),
        (
            Relation("prom", "promep", "prom", "promep", "_", RelationType.peer),
            "anb",
            "prom",
            False,
            False,
        ),
        (
            Relation("prom", "promep", "prom", "promep", "_", RelationType.peer),
            "prom",
            "abd",
            False,
            False,
        ),
        (
            Relation("prom", "promep", "prom", "promep", "_", RelationType.peer),
            "de",
            "fgh",
            False,
            False,
        ),
    ),
)
def test_match_endpoint_peer(rel, ep1, ep2, match, flip, unit, endpoint1, endpoint2):
    if unit is not None:
        ep1 = ep1 + f"/{unit}"
    if endpoint1:
        ep1 = ep1 + f":{endpoint1}"
    if ep2 and endpoint2:
        ep2 = ep2 + f":{endpoint2}"

    rep1 = RelationEndpointURL(ep1)
    rep2 = RelationEndpointURL(ep2) if ep2 else None
    assert _match_endpoint(rel, rep1, rep2) == (match, flip)


@pytest.mark.parametrize(
    "unit, endpoint1, endpoint2, match, flip",
    (
        (0, "kuzz", "kuzz", False, False),
        (None, "kuzz", "kuzz", False, False),
        (None, "promep", "kuzz", False, False),
        (None, "kuzz", "promep", False, False),
    ),
)
def test_match_endpoint_peer_underspecified_endpoint(
    unit, endpoint1, endpoint2, match, flip
):
    rel = Relation("prom", "promep", "prom", "promep", "_", RelationType.peer)
    ep1 = "prom"
    ep2 = "prom"
    if unit is not None:
        ep1 = ep1 + f"/{unit}"
    if endpoint1:
        ep1 = ep1 + f":{endpoint1}"
    if ep2 and endpoint2:
        ep2 = ep2 + f":{endpoint2}"

    rep1 = RelationEndpointURL(ep1)
    rep2 = RelationEndpointURL(ep2) if ep2 else None
    assert _match_endpoint(rel, rep1, rep2) == (match, flip)
