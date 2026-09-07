"""Compact inspection metadata derived from the formal JSON Schema."""


def schema_type_label(schema: dict) -> str:
    variants = schema.get("anyOf") or schema.get("oneOf")
    if variants:
        return " | ".join(dict.fromkeys(schema_type_label(item) for item in variants))
    kind = schema.get("type")
    if isinstance(kind, list):
        return " | ".join(kind)
    if kind == "array":
        return f"array<{schema_type_label(schema.get('items', {}))}>"
    return kind or ("object" if "properties" in schema else "unknown")


def parameter_summary(schema: dict, required: bool) -> dict:
    summary = {
        "type": schema_type_label(schema),
        "description": schema.get("description", ""),
        "required": required,
    }
    # Retain the formal branches and constraints instead of flattening nullable
    # integers/arrays to string. Existing consumers can still use the type label.
    for key in ("anyOf", "oneOf", "items", "enum", "default", "minimum", "maximum",
                "exclusiveMinimum", "exclusiveMaximum", "minItems", "maxItems"):
        if key in schema:
            summary[key] = schema[key]
    return summary
