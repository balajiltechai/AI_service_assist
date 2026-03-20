"""
Ingests OpenAPI 2.0 / 3.x specs (JSON or YAML) and extracts structured endpoint data.
"""
import json
import yaml
from typing import Dict, Any, List, Optional
from backend.models.schemas import EndpointDoc


def parse_openapi(content: str) -> Dict[str, Any]:
    """Parse JSON or YAML OpenAPI spec into a dict."""
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return yaml.safe_load(content)


def _resolve_ref(spec: Dict, ref: str) -> Dict:
    """Simple $ref resolver for local references."""
    if not ref.startswith("#/"):
        return {}
    parts = ref[2:].split("/")
    node = spec
    for part in parts:
        node = node.get(part, {})
    return node


def _extract_auth(spec: Dict, operation: Dict) -> str:
    """Derive authentication requirements from security definitions."""
    security = operation.get("security") or spec.get("security") or []
    if not security:
        components = spec.get("components", spec.get("securityDefinitions", {}))
        schemes = components.get("securitySchemes", components) if isinstance(components, dict) else {}
        if not schemes:
            return "None"
    scheme_names = []
    for item in security:
        scheme_names.extend(item.keys())
    if not scheme_names:
        return "None"

    # Try to get descriptions from spec
    all_schemes = (
        spec.get("components", {}).get("securitySchemes", {})
        or spec.get("securityDefinitions", {})
    )
    descriptions = []
    for name in scheme_names:
        scheme = all_schemes.get(name, {})
        stype = scheme.get("type", name)
        scheme_in = scheme.get("in", "")
        if stype == "http":
            descriptions.append(f"HTTP {scheme.get('scheme', 'bearer').title()}")
        elif stype == "apiKey":
            descriptions.append(f"API Key (in {scheme_in})")
        elif stype == "oauth2":
            descriptions.append("OAuth2")
        else:
            descriptions.append(stype or name)
    return ", ".join(descriptions) if descriptions else "Required"


def _extract_sample_request(operation: Dict, spec: Dict) -> Optional[str]:
    """Extract a sample request body if available."""
    req_body = operation.get("requestBody", {})
    if not req_body:
        # OpenAPI 2
        params = operation.get("parameters", [])
        body_params = [p for p in params if p.get("in") == "body"]
        if body_params:
            schema = body_params[0].get("schema", {})
            example = schema.get("example")
            if example:
                return json.dumps(example, indent=2)
        return None

    content = req_body.get("content", {})
    for media_type, media_obj in content.items():
        example = media_obj.get("example")
        if example:
            return json.dumps(example, indent=2)
        examples = media_obj.get("examples", {})
        if examples:
            first = next(iter(examples.values()))
            val = first.get("value")
            if val:
                return json.dumps(val, indent=2)
        schema = media_obj.get("schema", {})
        if "$ref" in schema:
            schema = _resolve_ref(spec, schema["$ref"])
        ex = schema.get("example")
        if ex:
            return json.dumps(ex, indent=2)
    return None


def _extract_sample_response(operation: Dict, spec: Dict) -> Optional[str]:
    """Extract a sample success response if available."""
    responses = operation.get("responses", {})
    for code in ["200", "201", "202"]:
        resp = responses.get(code, {})
        if not resp:
            continue
        content = resp.get("content", {})
        for media_type, media_obj in content.items():
            example = media_obj.get("example")
            if example:
                return json.dumps(example, indent=2)
            schema = media_obj.get("schema", {})
            if "$ref" in schema:
                schema = _resolve_ref(spec, schema["$ref"])
            ex = schema.get("example")
            if ex:
                return json.dumps(ex, indent=2)
        # OpenAPI 2
        schema = resp.get("schema", {})
        if "$ref" in schema:
            schema = _resolve_ref(spec, schema["$ref"])
        ex = schema.get("example")
        if ex:
            return json.dumps(ex, indent=2)
    return None


def extract_endpoints(spec: Dict) -> List[EndpointDoc]:
    """Extract all endpoints from an OpenAPI spec."""
    endpoints = []
    paths = spec.get("paths", {})

    for path, path_item in paths.items():
        for method in ["get", "post", "put", "patch", "delete", "head", "options"]:
            operation = path_item.get(method)
            if not operation:
                continue

            deprecated = operation.get("deprecated", False)
            auth = _extract_auth(spec, operation)
            sample_req = _extract_sample_request(operation, spec)
            sample_resp = _extract_sample_response(operation, spec)

            endpoints.append(EndpointDoc(
                method=method.upper(),
                path=path,
                summary=operation.get("summary"),
                description=operation.get("description"),
                parameters=operation.get("parameters"),
                request_body=operation.get("requestBody"),
                responses=operation.get("responses"),
                authentication=auth,
                sample_request=sample_req,
                sample_response=sample_resp,
                is_documented=True,
                is_deprecated=deprecated,
                deprecation_notice="This endpoint is deprecated." if deprecated else None,
                tags=operation.get("tags"),
            ))

    return endpoints


def extract_service_info(spec: Dict) -> Dict[str, Any]:
    """Extract top-level service metadata."""
    info = spec.get("info", {})
    servers = spec.get("servers", [])
    base_url = servers[0].get("url") if servers else spec.get("host", "")

    return {
        "name": info.get("title", "Unknown Service"),
        "version": info.get("version", "unknown"),
        "description": info.get("description"),
        "base_url": base_url,
        "contact": info.get("contact"),
        "license": info.get("license"),
        "tags": [t.get("name") for t in spec.get("tags", [])],
    }
