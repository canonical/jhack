import enum
import json
from collections import defaultdict
from typing import Iterable, List, Optional, TypedDict

import typer
from rich.console import Console
from rich.style import Style
from rich.text import Text

from jhack.helpers import ColorOption, RichSupportedColorOptions, Target
from jhack.logger import logger as jhack_logger
from jhack.utils.charm_rpc import _encode, _exec_crpc_expr

logger = jhack_logger.getChild("sitrep")


class _Format(enum.Enum):
    pprint = "pprint"
    json = "json"


class _RawStatus(TypedDict):
    name: str
    message: str


def _status_report(target: Target, model: str, app: bool = False) -> List[_RawStatus]:
    status_owner = "app" if app else "unit"
    expr = rf"ops.charm._evaluate_status(self) or output([{{'name': s.name, 'message': s.message}} for s in self.{status_owner}._collected_statuses])"
    out = _exec_crpc_expr(
        target=target,
        model=model,
        expr=_encode(expr),
        event="update-status",
        print_output=False,
    )
    return out


def _get_status(
    target,
    model: Optional[str] = None,
    fmt: _Format = _Format.pprint,
    app: bool = False,
    color: RichSupportedColorOptions = "auto",
):
    logger.info(f"collecting statuses from {target.unit_name}...")
    sr = _status_report(target, model, app=app)
    if not sr:
        exit(f"unable to gather status report from {target}")

    logger.info(f"formatting {len(sr)} statuses...")
    tree = _StatusTree(map(_Status, sr), color=color)
    tree.pprint(fmt, target, app)


class _Status:
    def __init__(self, raw: _RawStatus):
        self.name = raw["name"]
        path, _, msg = raw["message"].rpartition("]")
        self.message = msg.strip()
        raw_path = path.strip("[]")
        self.raw_path = raw_path
        self.path = tuple(raw_path.split("."))

    def __repr__(self):
        return f"[{self.raw_path}] {self.message}"

    def to_dict(self):
        return {
            "name": self.name,
            "message": self.message,
            "path": self.path,
        }


_status_name_to_color = {
    "unknown": "white",
    "active": "green",
    "blocked": "red",
    "waiting": "yellow",
    "maintenance": "blue",
    "foo": "green",
}


_status_name_to_symbol = {
    "unknown": "⊝",
    "active": "⊚",
    "blocked": "⊗",
    "waiting": "⊙",
    "maintenance": "⊕",
    "foo": "0",
}

_status_name_to_short = {
    "unknown": "????",
    "active": "actv",
    "blocked": "blck",
    "waiting": "wait",
    "maintenance": "mant",
    "foo": "foo",
}


class _StatusTree:
    def __init__(self, statuses: Iterable[_Status], color: RichSupportedColorOptions = "auto"):
        self._statuses = _statuses = list(statuses)

        tree = defaultdict(list)
        for s in _statuses:
            tree[s.path].append(s)
        self._color = color if color != "no" else None
        self._tree = tree

    def _fmt_pprint(self, target: Target = None, app: bool = False):
        console = Console(color_system=self._color)

        tree = self._tree
        # sort tree by path
        statuses: List[_Status]
        previous_path = ("",)
        indent = 0

        console.print(
            Text("<sitrep v0.1>  ", style=Style(bold=True, color="cyan"))
            + Text(f"{target.unit_name} {'app' if app else 'unit'} status tree: ")
        )

        console.print("[.]")  # root status first
        sorted_statuses = sorted(tree.items(), key=lambda x: x[0])
        for path, statuses in sorted_statuses:
            overlap = 0
            for i, j in zip(path, previous_path):
                if i == j:
                    overlap += 1
                else:
                    break

            remains = path[overlap:]
            if len(path) > len(previous_path):
                # child
                indent += 1
            elif len(path) == len(previous_path) and not remains:
                # sibling
                pass  # indent remains the same
            else:
                # indent is the amount of shared path
                indent = overlap

            if remains:
                base = "\t" * indent
                category_name = "." + ".".join(remains)
                txt = base + f"[{category_name}]"
                console.print(txt, style=Style(bold=(not path)))

            for status in statuses:
                symbol = _status_name_to_symbol[status.name]
                short_status_name = _status_name_to_short[status.name]
                prefix = f"{symbol} ({short_status_name})"
                color = _status_name_to_color[status.name]

                console.print(
                    Text("\t" * indent + "  " + prefix + "  ", style=Style(color=color))
                    + Text(status.message or "''"),
                    style=Style(bold=True),
                )
            previous_path = path

    def _fmt_json(self):
        data = [s.to_dict() for s in self._statuses]
        Console(color_system=self._color).print_json(json.dumps(data, indent=2))

    def pprint(self, fmt: _Format, target: Target = None, app: bool = False):
        if fmt is _Format.pprint:
            return self._fmt_pprint(target=target, app=app)
        elif fmt is _Format.json:
            return self._fmt_json()
        else:
            raise RuntimeError(f"unrecognized format option {fmt}")


def sitrep(
    target: str = typer.Argument(
        ...,
        help="Target unit name.",
    ),
    model: str = typer.Option(None, "-m", "--model", help="Which model to apply the command to."),
    fmt: _Format = typer.Option("pprint", "--format", help="Output format."),
    app: bool = typer.Option(False, "--app", is_flag=True, help="Use application status."),
    color: Optional[str] = ColorOption,
):
    """Gathers the status of the unit and prints it out."""
    return _get_status(target=Target.from_name(target), model=model, fmt=fmt, app=app, color=color)


if __name__ == "__main__":
    _get_status(Target.from_name("tempo/0"))
    # _StatusTree(
    #     statuses=[
    #         _Status({"name": "active", "message": "[a.b] qux"}),
    #         _Status({"name": "active", "message": "[a] bar"}),
    #         _Status({"name": "active", "message": "[a.b] baz"}),
    #         _Status({"name": "active", "message": "[a.b.bye] rubb"}),
    #         _Status({"name": "blocked", "message": "foo"}),
    #         _Status({"name": "active", "message": "[a.c] bor"}),
    #         _Status({"name": "active", "message": "[d] bor"}),
    #         _Status({"name": "active", "message": "[a.c.lob.panda] bor"}),
    #         _Status(
    #             {"name": "active", "message": "[a.c.lob.panda.lost.in.space.x] bor"}
    #         ),
    #         _Status({"name": "active", "message": "[d.e] ked"}),
    #     ]
    # ).pprint(_Format.pprint)
