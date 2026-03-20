"""
AI Solution for Service Documentation & Change Intelligence
FastAPI backend — main entry point
"""
import json
import logging
from contextlib import asynccontextmanager
from typing import Optional, List

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pathlib import Path

from backend.config import get_settings
from backend.storage import database as db
from backend import api_platform_client as registry
from backend.models.schemas import (
    IngestRequest, GenerateDocRequest, ExplainServiceRequest,
    CompareServicesRequest, ChangeLogRequest, PublishDocRequest,
    ServiceDoc, ChangeLog, GapReport, ArtifactType,
)
from backend.ingestors import openapi_ingestor, git_ingestor, log_ingestor, schema_ingestor
from backend.generators import doc_generator, change_generator
from backend.detectors import gap_detector


logging.basicConfig(level=get_settings().log_level)
logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    logger.info("Database initialized")
    yield


app = FastAPI(
    title="AI Service Documentation & Change Intelligence",
    description="Continuously generate and maintain service documentation using AI",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Serve frontend ────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def serve_frontend():
    return FileResponse(FRONTEND_DIR / "index.html")

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ─── Ingest ────────────────────────────────────────────────────────────────────

@app.post("/api/ingest", summary="Ingest a service artifact")
async def ingest(request: IngestRequest):
    """
    Ingest a service artifact (OpenAPI spec, Git URL, logs, schema).
    Registers the service in APIPlatform and stores the spec/traffic there.
    """
    parsed_metadata = request.metadata or {}
    content = request.content

    if request.artifact_type == ArtifactType.openapi:
        try:
            spec = openapi_ingestor.parse_openapi(content)
            info = openapi_ingestor.extract_service_info(spec)
            parsed_metadata.update({"parsed_info": info, "endpoint_count": len(spec.get("paths", {}))})
        except Exception as e:
            raise HTTPException(400, f"Failed to parse OpenAPI spec: {e}")

        # Register service + upload spec to APIPlatform
        await registry.register_service(
            service_id=request.service_id,
            name=request.service_name,
            version=request.version,
            description=info.get("description"),
            base_url=info.get("base_url"),
            tags=info.get("tags", []),
        )
        await registry.upload_spec(
            service_id=request.service_id,
            version=request.version,
            content=content,
            artifact_type="openapi",
        )

    elif request.artifact_type == ArtifactType.logs:
        result = log_ingestor.ingest_logs(content)
        if result.get("error"):
            raise HTTPException(400, result["error"])

        # Ensure service exists in APIPlatform before adding traffic
        existing = await registry.get_service(request.service_id)
        if not existing:
            await registry.register_service(
                service_id=request.service_id,
                name=request.service_name,
                version=request.version,
            )

        # Upload traffic to APIPlatform
        await registry.add_traffic(request.service_id, result["endpoints"])
        parsed_metadata.update({"traffic_summary": {
            "total_requests": result["total_requests"],
            "unique_endpoints": result["unique_endpoints"],
        }})

    elif request.artifact_type == ArtifactType.schema:
        schema_info = schema_ingestor.ingest_schema(content)
        if schema_info.get("error"):
            raise HTTPException(400, schema_info["error"])
        parsed_metadata.update({"schema_info": schema_info})
        await registry.register_service(
            service_id=request.service_id,
            name=request.service_name,
            version=request.version,
        )

    elif request.artifact_type == ArtifactType.git:
        git_data = git_ingestor.ingest_from_url(content)
        if git_data.get("error"):
            raise HTTPException(400, git_data["error"])

        await registry.register_service(
            service_id=request.service_id,
            name=request.service_name,
            version=request.version,
        )

        # If there's an embedded OpenAPI spec, upload it too
        if git_data.get("openapi_in_repo"):
            await registry.upload_spec(
                service_id=request.service_id,
                version=request.version,
                content=git_data["openapi_in_repo"],
                artifact_type="openapi",
            )

        parsed_metadata.update({"git_summary": {
            "commits": len(git_data.get("commits", [])),
            "tags": git_data.get("tags", []),
            "total_files": git_data.get("total_files", 0),
        }})
        content = json.dumps(git_data)

    elif request.artifact_type == ArtifactType.registry:
        # Registry metadata — register/update service in APIPlatform
        try:
            meta = json.loads(content)
        except json.JSONDecodeError:
            meta = {}
        await registry.register_service(
            service_id=request.service_id,
            name=request.service_name,
            version=request.version,
            description=meta.get("description"),
            base_url=meta.get("base_url"),
            tags=meta.get("tags", []),
        )
        parsed_metadata.update(meta)

    else:
        # For any other type, at minimum register the service
        await registry.register_service(
            service_id=request.service_id,
            name=request.service_name,
            version=request.version,
        )

    return {
        "status": "ingested",
        "service_id": request.service_id,
        "version": request.version,
        "artifact_type": request.artifact_type,
        "metadata": parsed_metadata,
    }


@app.post("/api/ingest/file", summary="Ingest a service artifact from file upload")
async def ingest_file(
    service_id: str = Form(...),
    service_name: str = Form(...),
    version: str = Form(...),
    artifact_type: ArtifactType = Form(...),
    file: UploadFile = File(...),
):
    content = (await file.read()).decode("utf-8", errors="replace")
    req = IngestRequest(
        service_id=service_id,
        service_name=service_name,
        version=version,
        artifact_type=artifact_type,
        content=content,
    )
    return await ingest(req)


# ─── Generate Documentation ────────────────────────────────────────────────────

@app.post("/api/generate", summary="Generate AI documentation for a service")
async def generate_docs(request: GenerateDocRequest):
    """
    Generate full documentation for a service using Claude.
    Fetches the spec from APIPlatform; stores generated docs in SQLite.
    """
    service = await registry.get_service(request.service_id)
    if not service:
        raise HTTPException(404, f"Service '{request.service_id}' not found. Ingest it first.")

    version = request.version or service["latest_version"]

    # Check if already generated
    if not request.regenerate:
        existing = await db.get_service_doc(request.service_id, version)
        if existing:
            return {"status": "cached", "service_id": request.service_id, "version": version,
                    "doc": existing["doc"]}

    # Fetch spec from APIPlatform
    spec_record = await registry.get_spec(request.service_id, version)
    if not spec_record:
        # Try without version (latest)
        spec_record = await registry.get_spec(request.service_id)
    if not spec_record:
        raise HTTPException(404, f"No spec found for service '{request.service_id}' v{version}. Ingest it first.")

    artifact_type = spec_record.get("artifact_type", "openapi")
    raw_content = spec_record["content"]

    # Extract endpoints if OpenAPI
    endpoints = []
    service_info = {}
    if artifact_type == ArtifactType.openapi or artifact_type == "openapi":
        try:
            spec = openapi_ingestor.parse_openapi(raw_content)
            endpoints = openapi_ingestor.extract_endpoints(spec)
            service_info = openapi_ingestor.extract_service_info(spec)
        except Exception as e:
            logger.warning(f"Could not parse OpenAPI for endpoint extraction: {e}")

    # Generate service summary
    logger.info(f"Generating docs for {request.service_id} v{version}")
    summary_data = doc_generator.generate_service_summary(
        name=service["name"],
        version=version,
        raw_spec=raw_content[:8000],
        artifact_type=artifact_type,
        extra_context=service_info.get("description") or service.get("description"),
    )

    # Enrich endpoints with LLM
    enriched_endpoints = []
    if endpoints:
        enriched_endpoints = doc_generator.generate_endpoint_docs(
            service_name=service["name"],
            endpoints=endpoints,
            service_context=summary_data.get("summary", ""),
        )

    def _sanitize_ep(ep_dict):
        for field in ("sample_request", "sample_response"):
            v = ep_dict.get(field)
            if isinstance(v, (dict, list)):
                ep_dict[field] = json.dumps(v, indent=2)
        return ep_dict

    from datetime import datetime
    doc = ServiceDoc(
        service_id=request.service_id,
        name=service["name"],
        version=version,
        summary=summary_data.get("summary"),
        description=summary_data.get("description"),
        base_url=service_info.get("base_url") or service.get("base_url"),
        endpoints=[_sanitize_ep(ep.model_dump()) for ep in enriched_endpoints],
        authentication_requirements=summary_data.get("authentication_requirements"),
        capabilities=summary_data.get("capabilities", []),
        tags=service_info.get("tags", []) or service.get("tags", []),
        generated_at=datetime.utcnow(),
        source_artifact=artifact_type,
    )

    doc_json = doc.model_dump_json()
    await db.save_service_doc(request.service_id, version, doc_json)

    return {"status": "generated", "service_id": request.service_id, "version": version,
            "doc": doc.model_dump()}


# ─── Stats ──────────────────────────────────────────────────────────────────────

@app.get("/api/stats", summary="Aggregate platform stats for the Demo page")
async def get_stats():
    """Returns live counts: services, documented, undocumented, total endpoints."""
    services = await registry.list_services()
    service_ids = [s["service_id"] for s in services]
    doc_status = await db.get_doc_status(service_ids)

    documented = sum(1 for sid in service_ids if doc_status.get(sid, {}).get("doc_count", 0) > 0)
    undocumented = len(service_ids) - documented

    # Sum endpoints across all services from APIPlatform
    endpoint_counts = []
    for sid in service_ids:
        eps = await registry.get_endpoints(sid)
        endpoint_counts.append(len(eps))
    total_endpoints = sum(endpoint_counts)

    return {
        "services_count": len(service_ids),
        "documented_count": documented,
        "undocumented_count": undocumented,
        "endpoints_count": total_endpoints,
    }


# ─── Retrieve Documentation ────────────────────────────────────────────────────

@app.get("/api/services", summary="List all registered services")
async def list_services():
    """Lists services from APIPlatform, enriched with doc status from SQLite."""
    services = await registry.list_services()

    # Enrich with doc status from SQLite
    service_ids = [s["service_id"] for s in services]
    doc_status = await db.get_doc_status(service_ids)

    result = []
    for svc in services:
        sid = svc["service_id"]
        status = doc_status.get(sid, {})
        result.append({
            **svc,
            "has_documentation": status.get("doc_count", 0) > 0,
            "last_updated": status.get("last_generated_at") or svc.get("updated_at"),
        })

    return {"services": result, "count": len(result)}


@app.get("/api/services/{service_id}", summary="Get service metadata")
async def get_service(service_id: str):
    service = await registry.get_service(service_id)
    if not service:
        raise HTTPException(404, f"Service '{service_id}' not found")
    versions = await registry.get_versions(service_id)
    return {**service, "versions": versions}


@app.get("/api/services/{service_id}/doc", summary="Get generated documentation")
async def get_doc(
    service_id: str,
    version: Optional[str] = Query(None, description="Specific version; defaults to latest"),
):
    if not version:
        service = await registry.get_service(service_id)
        if not service:
            raise HTTPException(404, f"Service '{service_id}' not found")
        version = service["latest_version"]

    doc = await db.get_service_doc(service_id, version)
    if not doc:
        raise HTTPException(404, "No documentation found. Run /api/generate first.")
    return doc["doc"]


@app.get("/api/services/{service_id}/versions", summary="List all versions")
async def get_versions(service_id: str):
    service = await registry.get_service(service_id)
    if not service:
        raise HTTPException(404, f"Service '{service_id}' not found")
    versions = await registry.get_versions(service_id)
    return {"service_id": service_id, "versions": versions}


# ─── Explain Service ────────────────────────────────────────────────────────────

@app.post("/api/explain", summary="Explain a service in plain language")
async def explain_service(request: ExplainServiceRequest):
    service = await registry.get_service(request.service_id)
    if not service:
        raise HTTPException(404, f"Service '{request.service_id}' not found")

    version = request.version or service["latest_version"]
    doc_record = await db.get_service_doc(request.service_id, version)
    if not doc_record:
        raise HTTPException(404, "No documentation found. Run /api/generate first.")

    async def generate():
        async for chunk in doc_generator.explain_service(
            service_doc=doc_record["doc"],
            question=request.question,
        ):
            yield chunk

    return StreamingResponse(generate(), media_type="text/plain")


# ─── Compare Services ────────────────────────────────────────────────────────────

@app.post("/api/compare", summary="Compare two services")
async def compare_services(request: CompareServicesRequest):
    svc_a = await registry.get_service(request.service_id_a)
    svc_b = await registry.get_service(request.service_id_b)
    if not svc_a:
        raise HTTPException(404, f"Service '{request.service_id_a}' not found")
    if not svc_b:
        raise HTTPException(404, f"Service '{request.service_id_b}' not found")

    version_a = request.version_a or svc_a["latest_version"]
    version_b = request.version_b or svc_b["latest_version"]

    doc_a = await db.get_service_doc(request.service_id_a, version_a)
    doc_b = await db.get_service_doc(request.service_id_b, version_b)

    if not doc_a:
        raise HTTPException(404, f"No doc for '{request.service_id_a}'. Run /api/generate first.")
    if not doc_b:
        raise HTTPException(404, f"No doc for '{request.service_id_b}'. Run /api/generate first.")

    async def generate():
        async for chunk in doc_generator.compare_services(doc_a["doc"], doc_b["doc"]):
            yield chunk

    return StreamingResponse(generate(), media_type="text/plain")


# ─── Change Log ────────────────────────────────────────────────────────────────

@app.post("/api/changelog", summary="Generate change log between two versions")
async def generate_changelog(request: ChangeLogRequest):
    service = await registry.get_service(request.service_id)
    if not service:
        raise HTTPException(404, f"Service '{request.service_id}' not found")

    # Check cache
    cached = await db.get_change_log(request.service_id, request.from_version, request.to_version)
    if cached:
        return {"status": "cached", **cached["changelog"]}

    doc_old = await db.get_service_doc(request.service_id, request.from_version)
    doc_new = await db.get_service_doc(request.service_id, request.to_version)

    if not doc_old:
        raise HTTPException(404, f"No doc for version '{request.from_version}'. Generate it first.")
    if not doc_new:
        raise HTTPException(404, f"No doc for version '{request.to_version}'. Generate it first.")

    changelog = change_generator.generate_change_log(
        service_id=request.service_id,
        service_name=service["name"],
        from_version=request.from_version,
        to_version=request.to_version,
        doc_old=doc_old["doc"],
        doc_new=doc_new["doc"],
    )

    await db.save_change_log(
        request.service_id, request.from_version, request.to_version,
        changelog.model_dump_json()
    )

    return {"status": "generated", **changelog.model_dump()}


# ─── Gap Detection ────────────────────────────────────────────────────────────

@app.get("/api/services/{service_id}/gaps", summary="Detect undocumented endpoints")
async def detect_gaps(
    service_id: str,
    version: Optional[str] = Query(None),
    with_recommendations: bool = Query(False),
):
    """
    Compare traffic logs (from APIPlatform) vs. documented endpoints (SQLite).
    Returns undocumented endpoints and missing documentation.
    """
    service = await registry.get_service(service_id)
    if not service:
        raise HTTPException(404, f"Service '{service_id}' not found")

    version = version or service["latest_version"]
    doc_record = await db.get_service_doc(service_id, version)
    if not doc_record:
        raise HTTPException(404, "No documentation found. Run /api/generate first.")

    # Fetch traffic from APIPlatform
    traffic_entries = await registry.get_traffic(service_id)
    if not traffic_entries:
        return {
            "service_id": service_id,
            "message": "No traffic logs found in APIPlatform. Ingest logs first via /api/ingest.",
            "undocumented_endpoints": [],
            "documentation_coverage_pct": 100.0,
        }

    # Aggregate hit counts per endpoint
    aggregated: dict = {}
    for entry in traffic_entries:
        key = (entry["method"].upper(), entry["path"])
        aggregated[key] = aggregated.get(key, 0) + entry.get("hit_count", 1)
    traffic = [{"method": m, "path": p, "total_hits": h} for (m, p), h in aggregated.items()]

    report = gap_detector.detect_gaps(traffic, doc_record["doc"])
    report["service_id"] = service_id

    await db.save_gap_report(service_id, json.dumps(report))

    if with_recommendations:
        recommendations = gap_detector.generate_gap_recommendations(report, service["name"])
        report["recommendations"] = recommendations

    return report


# ─── Publish ──────────────────────────────────────────────────────────────────

@app.post("/api/publish", summary="Publish documentation to portal/registry")
async def publish_docs(request: PublishDocRequest):
    service = await registry.get_service(request.service_id)
    if not service:
        raise HTTPException(404, f"Service '{request.service_id}' not found")

    version = request.version or service["latest_version"]
    doc = await db.get_service_doc(request.service_id, version)
    if not doc:
        raise HTTPException(404, "No documentation found. Generate it first.")

    from datetime import datetime
    return {
        "status": "published",
        "service_id": request.service_id,
        "version": version,
        "destination": request.destination,
        "published_at": datetime.utcnow().isoformat(),
        "doc_preview": {
            "name": doc["doc"].get("name"),
            "summary": doc["doc"].get("summary"),
            "endpoint_count": len(doc["doc"].get("endpoints", [])),
        },
        "message": f"Documentation for '{service['name']}' v{version} published to {request.destination}.",
    }


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/api/health", summary="Health check")
async def health():
    return {
        "status": "healthy",
        "model": get_settings().claude_model,
        "api_platform_url": get_settings().api_platform_url,
        "version": "1.0.0",
    }
