def emit_thing(v):
    if v.__class__.__name__ == "dict":
        return emit_dict(v)
    elif v.__class__.__name__ == "list":
        return emit_list(v)
    elif v.__class__.__name__ in {
        "Int64",
        "int",
        "long",
        "float",
        "decimal",
        "Decimal128",
        "Decimal",
    }:
        return str(v)
    elif v.__class__.__name__ == "datetime":
        return v
    else:
        return str(v)


def emit_list(ll: list) -> list:
    return list(map(emit_thing, ll))


def emit_dict(dd: dict) -> dict:
    out = {}
    for k, v in dd.items():
        out[k] = emit_thing(v)
    return out


def parse_eson(doc: str) -> dict:
    return emit_dict(doc)


import json
import re

from bson import json_util


def read_mongoextjson_file(filename):
    with open(filename, "r") as f:
        bsondata = f.read()
        # Convert Mongo object(s) to regular strict JSON
        jsondata = re.sub(
            r"ObjectId\s*\(\s*\"(\S+)\"\s*\)", r'{"$oid": "\1"}', bsondata
        )
        # Description of Mongo ObjectId:
        # https://docs.mongodb.com/manual/reference/mongodb-extended-json/#mongodb-bsontype-ObjectId
        # now we can parse this as JSON, and use MongoDB's object_hook
        data = json.loads(jsondata, object_hook=json_util.object_hook)
        return data
