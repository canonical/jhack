#!/usr/bin/env python3
import ast
from pathlib import Path

import asttokens
from astunparse import unparse

BACKEND_CALLS_TO_MEMOIZE = {
    "relation_ids",
    "relation_list",
    "relation_remote_app_name",
    "relation_get",
    "update_relation_data",
    "relation_set",
    "config_get",
    "is_leader",
    "application_version_set",
    "resource_get",
    "status_get",
    "status_set",
    "storage_list",
    "storage_get",
    "storage_add",
    "action_get",
    "action_set",
    "action_log",
    "action_fail",
    "network_get",
    "add_metrics",
    "juju_log",
    "planned_units",
    # 'secret_get',
    # 'secret_set',
    # 'secret_grant',
    # 'secret_remove',
}
storage = {}


def _is_model_backend(token: ast.AST):
    return isinstance(token, ast.ClassDef) and token.name == "_ModelBackend"


def _should_memoize(token: ast.AST):
    return isinstance(token, ast.FunctionDef) and token.name in BACKEND_CALLS_TO_MEMOIZE


memo_import_block = """
# ==== block added by jhack.replay -- memotools ===
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
"""


def inject_memoizer(source_file: Path):
    memo_token = (
        asttokens.ASTTokens("@memo()\ndef foo():...", parse=True)
        .tree.body[0]
        .decorator_list[0]
    )

    atok = asttokens.ASTTokens(source_file.read_text(), parse=True).tree
    model_backend = next(filter(_is_model_backend, atok.body))

    for method in filter(_should_memoize, model_backend.body):
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
