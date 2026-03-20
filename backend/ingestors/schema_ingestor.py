"""
Ingests dataset schemas (JSON Schema, Avro, Protobuf-like, or plain JSON).
Extracts field descriptions to feed into the documentation generator.
"""
import json
from typing import Dict, Any, List, Optional


def _flatten_json_schema(schema: Dict, prefix: str = "") -> List[Dict[str, Any]]:
    """Recursively flatten a JSON Schema into a list of field descriptors."""
    fields = []
    schema_type = schema.get("type", "object")
    properties = schema.get("properties", {})
    required_fields = schema.get("required", [])

    for name, prop in properties.items():
        full_name = f"{prefix}.{name}" if prefix else name
        field = {
            "name": full_name,
            "type": prop.get("type", prop.get("$ref", "any")),
            "description": prop.get("description", prop.get("title", "")),
            "required": name in required_fields,
            "format": prop.get("format"),
            "enum": prop.get("enum"),
            "example": prop.get("example"),
        }
        fields.append(field)

        # Recurse into nested objects
        if prop.get("type") == "object" and "properties" in prop:
            fields.extend(_flatten_json_schema(prop, full_name))
        elif prop.get("type") == "array":
            items = prop.get("items", {})
            if items.get("type") == "object":
                fields.extend(_flatten_json_schema(items, f"{full_name}[]"))

    return fields


def _parse_avro_schema(schema: Dict) -> List[Dict[str, Any]]:
    """Parse Avro schema fields."""
    fields = []
    for field in schema.get("fields", []):
        field_type = field.get("type", "null")
        if isinstance(field_type, list):
            field_type = [t for t in field_type if t != "null"]
            field_type = field_type[0] if field_type else "null"
        if isinstance(field_type, dict):
            field_type = field_type.get("type", "record")

        fields.append({
            "name": field.get("name", ""),
            "type": str(field_type),
            "description": field.get("doc", ""),
            "required": "null" not in (field.get("type") if isinstance(field.get("type"), list) else []),
            "default": field.get("default"),
        })
    return fields


def ingest_schema(content: str) -> Dict[str, Any]:
    """
    Parse and extract schema metadata from JSON Schema or Avro schema.
    Returns structured schema info for documentation generation.
    """
    try:
        schema = json.loads(content)
    except json.JSONDecodeError:
        return {"error": "Invalid JSON schema content", "fields": [], "schema_type": "unknown"}

    # Detect schema type
    if "$schema" in schema or "properties" in schema:
        schema_type = "json_schema"
        title = schema.get("title", schema.get("$id", "Unknown Schema"))
        description = schema.get("description", "")
        fields = _flatten_json_schema(schema)

    elif schema.get("type") in ("record", "enum", "array") and "name" in schema:
        schema_type = "avro"
        title = schema.get("name", "Unknown Schema")
        description = schema.get("doc", "")
        fields = _parse_avro_schema(schema)

    else:
        # Treat as plain JSON example — infer schema
        schema_type = "inferred"
        title = "Inferred Schema"
        description = "Schema inferred from JSON example"
        fields = []
        for key, value in schema.items():
            fields.append({
                "name": key,
                "type": type(value).__name__,
                "description": "",
                "required": True,
                "example": str(value)[:100] if not isinstance(value, (dict, list)) else None,
            })

    return {
        "schema_type": schema_type,
        "title": title,
        "description": description,
        "fields": fields,
        "field_count": len(fields),
    }
