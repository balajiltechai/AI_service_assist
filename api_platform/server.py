"""
Mock APIPlatform API Server — source of truth for service registry data.

Stores data in api_platform/registry_data.json (persisted across restarts).
Run on port 8001: python run_api_platform.py

/docs shows:
  - Platform Management sections (Services, Specs & Versions, Traffic, Health)
  - One section per registered service showing its actual API endpoints
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse
from pydantic import BaseModel


DATA_FILE = Path(__file__).parent / "registry_data.json"

app = FastAPI(
    title="APIPlatform Mock API",
    description=(
        "Service registry — source of truth for services, specs, versions, and traffic.\n\n"
        "**Platform Management** sections below show the registry CRUD APIs.\n\n"
        "**Service API** sections (one per registered service) show each service's actual endpoints "
        "parsed from their stored OpenAPI specs."
    ),
    version="1.0.0",
    docs_url=None,   # disable default — we serve a custom /docs
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory store (loaded from JSON file on startup) ────────────────────────

_store: Dict = {"services": {}, "specs": {}, "traffic": {}}


def _load():
    if DATA_FILE.exists():
        try:
            _store.update(json.loads(DATA_FILE.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, KeyError):
            pass


def _save():
    DATA_FILE.write_text(json.dumps(_store, indent=2), encoding="utf-8")


_load()


# ── Request models ────────────────────────────────────────────────────────────

class RegisterServiceRequest(BaseModel):
    service_id: str
    name: str
    version: str
    description: Optional[str] = None
    base_url: Optional[str] = None
    tags: Optional[List[str]] = []


class UploadSpecRequest(BaseModel):
    version: str
    content: str
    artifact_type: str = "openapi"
    metadata: Optional[Dict[str, Any]] = None


class TrafficEntry(BaseModel):
    method: str
    path: str
    hit_count: int = 1


# ── Service Registry endpoints ────────────────────────────────────────────────

@app.get("/services", summary="[Services] List all registered services", tags=["Platform Management"])
def list_services():
    svcs = list(_store["services"].values())
    return {"services": svcs, "count": len(svcs)}


@app.get("/services/{service_id}", summary="[Services] Get service metadata", tags=["Platform Management"])
def get_service(service_id: str):
    svc = _store["services"].get(service_id)
    if not svc:
        raise HTTPException(404, f"Service '{service_id}' not found")
    return svc


@app.post("/services", status_code=201, summary="[Services] Register or update a service", tags=["Platform Management"])
def register_service(req: RegisterServiceRequest):
    now = datetime.utcnow().isoformat()
    existing = _store["services"].get(req.service_id)
    _store["services"][req.service_id] = {
        "service_id": req.service_id,
        "name": req.name,
        "latest_version": req.version,
        "description": req.description,
        "base_url": req.base_url,
        "tags": req.tags or [],
        "created_at": existing["created_at"] if existing else now,
        "updated_at": now,
    }
    _save()
    return _store["services"][req.service_id]


@app.get("/services/{service_id}/endpoints", summary="[Services] List all API endpoints from spec", tags=["Platform Management"])
def get_endpoints(service_id: str, version: Optional[str] = None):
    if service_id not in _store["services"]:
        raise HTTPException(404, f"Service '{service_id}' not found")

    latest_version = _store["services"][service_id]["latest_version"]
    target_version = version or latest_version
    spec_versions = _store["specs"].get(service_id, {})
    raw = spec_versions.get(target_version) or (list(spec_versions.values())[-1] if spec_versions else None)

    if not raw:
        return {"service_id": service_id, "version": target_version, "endpoints": [], "count": 0}

    try:
        spec = json.loads(raw)
    except json.JSONDecodeError:
        return {"service_id": service_id, "version": target_version, "endpoints": [], "count": 0}

    endpoints = []
    for path, path_item in spec.get("paths", {}).items():
        for method, operation in path_item.items():
            if method.upper() not in ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"):
                continue
            endpoints.append({
                "method": method.upper(),
                "path": path,
                "summary": operation.get("summary", ""),
                "description": operation.get("description"),
                "tags": operation.get("tags", []),
                "deprecated": operation.get("deprecated", False),
                "parameters": operation.get("parameters", []),
                "security": operation.get("security"),
            })

    return {"service_id": service_id, "version": target_version, "endpoints": endpoints, "count": len(endpoints)}


# ── Specs & Versions endpoints ────────────────────────────────────────────────

@app.get("/services/{service_id}/versions", summary="[Specs & Versions] List all versions", tags=["Platform Management"])
def get_versions(service_id: str):
    if service_id not in _store["services"]:
        raise HTTPException(404, f"Service '{service_id}' not found")
    versions = list(_store["specs"].get(service_id, {}).keys())
    return {"service_id": service_id, "versions": versions}


@app.get("/services/{service_id}/spec", summary="[Specs & Versions] Get latest spec", tags=["Platform Management"])
def get_latest_spec(service_id: str):
    if service_id not in _store["services"]:
        raise HTTPException(404, f"Service '{service_id}' not found")
    latest_version = _store["services"][service_id]["latest_version"]
    spec_versions = _store["specs"].get(service_id, {})
    content = spec_versions.get(latest_version) or (list(spec_versions.values())[-1] if spec_versions else None)
    if not content:
        raise HTTPException(404, "No spec found for this service")
    return {"service_id": service_id, "version": latest_version, "content": content, "artifact_type": "openapi"}


@app.get("/services/{service_id}/spec/{version}", summary="[Specs & Versions] Get spec by version", tags=["Platform Management"])
def get_spec_version(service_id: str, version: str):
    if service_id not in _store["services"]:
        raise HTTPException(404, f"Service '{service_id}' not found")
    content = _store["specs"].get(service_id, {}).get(version)
    if not content:
        raise HTTPException(404, f"No spec found for version '{version}'")
    return {"service_id": service_id, "version": version, "content": content, "artifact_type": "openapi"}


@app.post("/services/{service_id}/spec", status_code=201, summary="[Specs & Versions] Upload a spec version", tags=["Platform Management"])
def upload_spec(service_id: str, req: UploadSpecRequest):
    if service_id not in _store["services"]:
        raise HTTPException(404, f"Service '{service_id}' not found")
    if service_id not in _store["specs"]:
        _store["specs"][service_id] = {}
    _store["specs"][service_id][req.version] = req.content
    _store["services"][service_id]["latest_version"] = req.version
    _store["services"][service_id]["updated_at"] = datetime.utcnow().isoformat()
    _save()
    return {"service_id": service_id, "version": req.version, "artifact_type": req.artifact_type, "status": "uploaded"}


# ── Traffic endpoints ─────────────────────────────────────────────────────────

@app.get("/services/{service_id}/traffic", summary="[Traffic] Get traffic log entries", tags=["Platform Management"])
def get_traffic(service_id: str):
    if service_id not in _store["services"]:
        raise HTTPException(404, f"Service '{service_id}' not found")
    entries = _store["traffic"].get(service_id, [])
    return {"service_id": service_id, "entries": entries, "count": len(entries)}


@app.post("/services/{service_id}/traffic", status_code=201, summary="[Traffic] Add traffic log entries", tags=["Platform Management"])
def add_traffic(service_id: str, entries: List[TrafficEntry]):
    if service_id not in _store["services"]:
        raise HTTPException(404, f"Service '{service_id}' not found")
    if service_id not in _store["traffic"]:
        _store["traffic"][service_id] = []
    for e in entries:
        _store["traffic"][service_id].append({
            "method": e.method,
            "path": e.path,
            "hit_count": e.hit_count,
        })
    _save()
    return {"status": "added", "count": len(entries)}


# ── Health & Root ─────────────────────────────────────────────────────────────

@app.get("/health", summary="[Health] Platform health check", tags=["Platform Management"])
def health():
    return {
        "status": "healthy",
        "service": "APIPlatform Mock API",
        "version": "1.0.0",
        "services_registered": len(_store["services"]),
    }


@app.get("/", include_in_schema=False)
def root():
    return {
        "service": "APIPlatform Mock API",
        "version": "1.0.0",
        "status": "healthy",
        "services_registered": len(_store["services"]),
        "endpoints": {"services": "/services", "health": "/health", "docs": "/docs"},
    }


@app.get("/docs", include_in_schema=False)
async def custom_docs():
    services = list(_store["services"].values())
    service_count = len(services)

    def _count_endpoints(service_id):
        versions = _store["specs"].get(service_id, {})
        if not versions:
            return 0
        raw = next(iter(versions.values()), None)
        if not raw:
            return 0
        try:
            spec = json.loads(raw)
        except json.JSONDecodeError:
            return 0
        http_methods = {"get", "post", "put", "patch", "delete"}
        return sum(
            len([m for m in path_item if m in http_methods])
            for path_item in spec.get("paths", {}).values()
        )

    endpoint_count = sum(_count_endpoints(s["service_id"]) for s in services)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>APIPlatform — Service Registry</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css"/>
  <style>
    /* ── Base ── */
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'Inter', 'Segoe UI', sans-serif; background: #0f1117; color: #e2e8f0; }}

    /* ── Top navbar ── */
    .ap-navbar {{
      background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
      border-bottom: 1px solid #334155;
      padding: 0 32px;
      display: flex;
      align-items: center;
      gap: 16px;
      height: 60px;
      position: sticky;
      top: 0;
      z-index: 1000;
      box-shadow: 0 2px 20px rgba(0,0,0,0.4);
    }}
    .ap-logo {{
      font-size: 20px;
      font-weight: 700;
      color: #fff;
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .ap-logo-icon {{
      width: 32px; height: 32px;
      background: linear-gradient(135deg, #6366f1, #8b5cf6);
      border-radius: 8px;
      display: flex; align-items: center; justify-content: center;
      font-size: 16px;
    }}
    .ap-badge {{
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 20px;
      padding: 3px 12px;
      font-size: 12px;
      color: #94a3b8;
    }}
    .ap-stats {{
      margin-left: auto;
      display: flex;
      gap: 24px;
    }}
    .ap-stat {{
      text-align: center;
    }}
    .ap-stat-value {{
      font-size: 18px;
      font-weight: 700;
      color: #6366f1;
    }}
    .ap-stat-label {{
      font-size: 11px;
      color: #64748b;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}

    /* ── Swagger UI overrides ── */
    .swagger-ui {{ background: transparent; }}
    .swagger-ui .topbar {{ display: none; }}
    .swagger-ui .info {{ margin: 24px 0 8px; }}
    .swagger-ui .info .title {{
      font-size: 26px !important;
      font-weight: 700 !important;
      color: #f1f5f9 !important;
    }}
    .swagger-ui .info .description p {{
      color: #94a3b8 !important;
      font-size: 14px !important;
      line-height: 1.6;
    }}
    .swagger-ui .info .description strong {{ color: #e2e8f0 !important; }}

    /* Tag sections */
    .swagger-ui .opblock-tag {{
      border: none !important;
      border-bottom: 1px solid #1e293b !important;
      margin: 4px 0 !important;
      padding: 10px 16px !important;
      border-radius: 10px !important;
      background: #1a2035 !important;
      transition: background 0.2s;
    }}
    .swagger-ui .opblock-tag:hover {{ background: #1e2a45 !important; }}
    .swagger-ui .opblock-tag a {{
      color: #e2e8f0 !important;
      font-size: 15px !important;
      font-weight: 600 !important;
    }}
    .swagger-ui .opblock-tag small {{
      color: #64748b !important;
      font-size: 12px !important;
    }}
    .swagger-ui section.models {{ display: none; }}

    /* Operation blocks */
    .swagger-ui .opblock {{
      border-radius: 8px !important;
      border: 1px solid #1e293b !important;
      margin: 6px 0 !important;
      box-shadow: none !important;
      overflow: hidden;
    }}
    .swagger-ui .opblock .opblock-summary {{
      padding: 10px 16px !important;
      border: none !important;
    }}
    .swagger-ui .opblock .opblock-summary-path {{
      font-size: 14px !important;
      font-weight: 500 !important;
      color: #e2e8f0 !important;
    }}
    .swagger-ui .opblock .opblock-summary-description {{
      color: #94a3b8 !important;
      font-size: 13px !important;
    }}

    /* Method badge colors */
    .swagger-ui .opblock-get    {{ background: rgba(16,185,129,0.08) !important; border-color: rgba(16,185,129,0.25) !important; }}
    .swagger-ui .opblock-post   {{ background: rgba(99,102,241,0.08) !important; border-color: rgba(99,102,241,0.25) !important; }}
    .swagger-ui .opblock-put    {{ background: rgba(245,158,11,0.08) !important; border-color: rgba(245,158,11,0.25) !important; }}
    .swagger-ui .opblock-patch  {{ background: rgba(139,92,246,0.08) !important; border-color: rgba(139,92,246,0.25) !important; }}
    .swagger-ui .opblock-delete {{ background: rgba(239,68,68,0.08)  !important; border-color: rgba(239,68,68,0.25)  !important; }}

    .swagger-ui .opblock-get    .opblock-summary-method {{ background: #10b981 !important; }}
    .swagger-ui .opblock-post   .opblock-summary-method {{ background: #6366f1 !important; }}
    .swagger-ui .opblock-put    .opblock-summary-method {{ background: #f59e0b !important; }}
    .swagger-ui .opblock-patch  .opblock-summary-method {{ background: #8b5cf6 !important; }}
    .swagger-ui .opblock-delete .opblock-summary-method {{ background: #ef4444 !important; }}

    .swagger-ui .opblock-summary-method {{
      border-radius: 6px !important;
      font-size: 11px !important;
      font-weight: 700 !important;
      min-width: 72px !important;
      padding: 5px 8px !important;
    }}

    /* Deprecated */
    .swagger-ui .opblock.opblock-deprecated {{
      opacity: 0.5 !important;
      border-style: dashed !important;
    }}

    /* Expand/collapse body */
    .swagger-ui .opblock-body {{
      background: #0f1117 !important;
      border-top: 1px solid #1e293b !important;
    }}
    .swagger-ui .opblock-section-header {{
      background: #1a2035 !important;
    }}
    .swagger-ui .opblock-section-header h4 {{
      color: #94a3b8 !important;
      font-size: 12px !important;
    }}

    /* Parameters */
    .swagger-ui table {{ background: transparent !important; }}
    .swagger-ui .parameter__name {{ color: #e2e8f0 !important; font-size: 13px !important; }}
    .swagger-ui .parameter__type {{ color: #6366f1 !important; font-size: 12px !important; }}
    .swagger-ui .parameter__in   {{ color: #64748b !important; font-size: 11px !important; }}
    .swagger-ui td, .swagger-ui th {{ border-color: #1e293b !important; color: #94a3b8 !important; }}

    /* Response codes */
    .swagger-ui .response-col_status {{ color: #10b981 !important; font-weight: 600 !important; }}
    .swagger-ui .responses-table .response-col_description {{ color: #94a3b8 !important; }}

    /* Buttons */
    .swagger-ui .btn.execute {{
      background: #6366f1 !important;
      border-color: #6366f1 !important;
      border-radius: 6px !important;
      font-weight: 600 !important;
    }}
    .swagger-ui .btn.execute:hover {{ background: #4f46e5 !important; }}
    .swagger-ui .try-out__btn {{
      border-color: #334155 !important;
      color: #94a3b8 !important;
      border-radius: 6px !important;
    }}

    /* Input fields */
    .swagger-ui input, .swagger-ui select, .swagger-ui textarea {{
      background: #1e293b !important;
      border-color: #334155 !important;
      color: #e2e8f0 !important;
      border-radius: 6px !important;
    }}

    /* Scrollbar */
    ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
    ::-webkit-scrollbar-track {{ background: #0f1117; }}
    ::-webkit-scrollbar-thumb {{ background: #334155; border-radius: 3px; }}

    /* Main container */
    #swagger-ui {{ max-width: 1200px; margin: 0 auto; padding: 0 24px 60px; }}
    .swagger-ui .wrapper {{ padding: 0 !important; }}
    .swagger-ui .scheme-container {{
      background: #1a2035 !important;
      border-radius: 10px !important;
      border: 1px solid #1e293b !important;
      padding: 12px 16px !important;
      margin-bottom: 16px !important;
      box-shadow: none !important;
    }}
    .swagger-ui .servers > label {{ color: #94a3b8 !important; font-size: 13px !important; }}
    .swagger-ui .servers select {{
      background: #0f1117 !important;
      border-color: #334155 !important;
      color: #e2e8f0 !important;
    }}

    /* Filter bar */
    .swagger-ui .filter .operation-filter-input {{
      background: #1e293b !important;
      border-color: #334155 !important;
      color: #e2e8f0 !important;
      border-radius: 8px !important;
    }}
  </style>
</head>
<body>
  <div class="ap-navbar">
    <div class="ap-logo">
      <div class="ap-logo-icon">&#9881;</div>
      APIPlatform
    </div>
    <span class="ap-badge">Service Registry</span>
    <span class="ap-badge">v1.0.0</span>
    <div class="ap-stats">
      <div class="ap-stat">
        <div class="ap-stat-value">{service_count}</div>
        <div class="ap-stat-label">Services</div>
      </div>
      <div class="ap-stat">
        <div class="ap-stat-value">{endpoint_count}</div>
        <div class="ap-stat-label">API Endpoints</div>
      </div>
      <div class="ap-stat">
        <div class="ap-stat-value">&#x2713;</div>
        <div class="ap-stat-label">Healthy</div>
      </div>
    </div>
  </div>

  <div id="swagger-ui"></div>

  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    SwaggerUIBundle({{
      url: "/openapi.json",
      dom_id: "#swagger-ui",
      presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
      layout: "BaseLayout",
      docExpansion: "list",
      defaultModelsExpandDepth: -1,
      filter: true,
      tryItOutEnabled: false,
      syntaxHighlight: {{ theme: "monokai" }},
      deepLinking: true,
    }});
  </script>
</body>
</html>"""
    return HTMLResponse(html)


# ── Custom OpenAPI schema — inject each service's APIs as separate sections ───

def _build_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    # Start with FastAPI's default schema (platform management routes)
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    # Tag ordering: single platform management section first, then one section per service
    tag_order = [
        {
            "name": "Platform Management",
            "description": (
                "Internal registry CRUD APIs used by ServiceAssist.\n\n"
                "**Subcategories:**\n\n"
                "| Prefix | Purpose |\n"
                "|---|---|\n"
                "| `[Services]` | Register, list, and query services |\n"
                "| `[Specs & Versions]` | Upload and retrieve OpenAPI specs per version |\n"
                "| `[Traffic]` | Ingest and query production traffic logs for gap detection |\n"
                "| `[Health]` | Platform health check |"
            ),
        },
    ]

    # Inject each registered service's endpoints as a tagged section
    http_methods = {"get", "post", "put", "patch", "delete", "options", "head"}

    for service_id, svc in _store["services"].items():
        name = svc.get("name", service_id)
        version = svc.get("latest_version", "")
        base_url = svc.get("base_url", "")
        description = svc.get("description", "")
        tag_name = f"{name} ({version})"

        tag_order.append({
            "name": tag_name,
            "description": (
                f"**Service ID:** `{service_id}`  \n"
                f"**Base URL:** `{base_url}`  \n"
                f"{description}"
            ),
        })

        # Parse the stored OpenAPI spec for this service
        raw = (_store["specs"].get(service_id, {}).get(version)
               or next(iter(_store["specs"].get(service_id, {}).values()), None))
        if not raw:
            continue

        try:
            svc_spec = json.loads(raw)
        except json.JSONDecodeError:
            continue

        # Inject each path/operation from the service spec into the merged schema
        for path, path_item in svc_spec.get("paths", {}).items():
            virtual_path = f"/~{service_id}{path}"
            schema.setdefault("paths", {})[virtual_path] = {}

            for method, operation in path_item.items():
                if method.lower() not in http_methods:
                    continue

                op = {
                    "summary": operation.get("summary") or f"{method.upper()} {path}",
                    "description": (
                        (operation.get("description") or "") +
                        f"\n\n> **Actual endpoint:** `{method.upper()} {base_url}{path}`"
                    ).strip(),
                    "tags": [tag_name],
                    "parameters": operation.get("parameters", []),
                    "deprecated": operation.get("deprecated", False),
                    "responses": operation.get("responses") or {"200": {"description": "Success"}},
                    "operationId": f"{service_id}__{method}__{path.replace('/', '_').strip('_')}",
                }
                if "requestBody" in operation:
                    op["requestBody"] = operation["requestBody"]

                schema["paths"][virtual_path][method] = op

    schema["tags"] = tag_order
    app.openapi_schema = schema
    return schema


app.openapi = _build_openapi
