def emit_thing(v):
    if v.__class__.__name__ == 'dict':
        return emit_dict(v)
    elif v.__class__.__name__ == 'list':
        return emit_list(v)
    elif v.__class__.__name__ in {'Int64', 'int', 'long', 'float', 'decimal', 'Decimal128', 'Decimal'}:
        return str(v)
    elif v.__class__.__name__ == 'datetime':
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
    return emit_dict()
