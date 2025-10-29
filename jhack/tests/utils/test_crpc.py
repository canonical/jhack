from unittest.mock import patch

import ops
import pytest

from jhack.utils.charm_rpc_dispatch import load_charm_type


def test_load_charm_type_simple():
    class MyMod:
        Foo = type("Foo", (ops.CharmBase,), {})

    with patch("importlib.import_module", return_value=MyMod):
        assert load_charm_type().__name__ == "Foo"


def test_load_charm_type_double_leaf():
    class MyMod:
        Foo = type("Foo", (ops.CharmBase,), {})
        Boo = type("Boo", (ops.CharmBase,), {})

    with patch("importlib.import_module", return_value=MyMod):
        with pytest.raises(RuntimeError, match="Multiple charm types found"):
            load_charm_type()


def test_load_charm_type_inherit():
    class MyMod:
        Foo = type("Foo", (ops.CharmBase,), {})
        Boo = type("Boo", (Foo,), {})

    with patch("importlib.import_module", return_value=MyMod):
        assert load_charm_type().__name__ == "Boo"


def test_load_charm_type_inherit_double():
    class MyMod:
        Foo = type("Foo", (ops.CharmBase,), {})
        Boo = type("Boo", (Foo,), {})
        Coo = type("Coo", (Foo,), {})

    with patch("importlib.import_module", return_value=MyMod):
        with pytest.raises(RuntimeError, match="Multiple charm types found"):
            load_charm_type()


def test_load_charm_type_double():
    class MyMod:
        Foo = type("Foo", (ops.CharmBase,), {})
        Boo = type("Boo", (Foo,), {})
        Coo = type("Coo", (ops.CharmBase,), {})

    with patch("importlib.import_module", return_value=MyMod):
        with pytest.raises(RuntimeError, match="Multiple charm types found"):
            load_charm_type()
