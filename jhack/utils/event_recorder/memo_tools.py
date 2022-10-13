#!/usr/bin/env python3
import ast
from functools import partial
from pathlib import Path
from textwrap import dedent
from typing import Sequence, Set, Dict, Union, FrozenSet

import asttokens
from astunparse import unparse

storage = {}

memo_import_block = dedent(
"""# ==== block added by jhack.replay -- memotools ===
try:
    from recorder import memo
except ModuleNotFoundError as e:
    msg = "recorder not installed. " \
          "This can happen if you're playing with Runtime in a local venv. " \
          "In that case all you have to do is ensure that the PYTHONPATH is patched to include the path to " \
          "recorder.py before loading this module. " \
          "Tread carefully."
    raise RuntimeError(msg) from e
# ==== end block ===
""")


def inject_memoizer(source_file: Path, decorate: Dict[str, Union[FrozenSet[str], Set[str], Sequence[str]]]):
    """Rewrite source_file by decorating methods in a number of classes.

    Decorate: a dict mapping class names to methods of that class that should be decorated.
    Example::
        >>> inject_memoizer(Path('foo.py'), {'MyClass': ['do_x', 'is_ready', 'refresh', 'bar']})
    """
    memo_token = (
        asttokens.ASTTokens("@memo()\ndef foo():...", parse=True)
        .tree.body[0]
        .decorator_list[0]
    )

    atok = asttokens.ASTTokens(source_file.read_text(), parse=True).tree

    def _should_decorate_class(token: ast.AST):
        return isinstance(token, ast.ClassDef) and token.name in decorate

    for cls in filter(_should_decorate_class, atok.body):
        def _should_decorate_method(token: ast.AST):
            return isinstance(token, ast.FunctionDef) and token.name in decorate[cls.name]

        for method in filter(_should_decorate_method, cls.body):
            existing_decorators = {
                token.first_token.string for token in method.decorator_list
            }
            # only add the decorator if the function is not already decorated:
            if memo_token.first_token.string not in existing_decorators:
                method.decorator_list.append(memo_token)

    unparsed_source = unparse(atok)
    if "from recorder import memo" not in unparsed_source:
        # only add the import if necessary:
        unparsed_source = memo_import_block + unparsed_source

    source_file.write_text(unparsed_source)
