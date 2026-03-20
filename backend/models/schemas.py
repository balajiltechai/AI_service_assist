import json as _json
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from enum import Enum


class ArtifactType(str, Enum):
    openapi = "openapi"
    git = "git"
    logs = "logs"
    schema = "schema"
    registry = "registry"


class EndpointDoc(BaseModel):
    method: str
    path: str
    summary: Optional[str] = None
    description: Optional[str] = None
    parameters: Optional[List[Dict[str, Any]]] = None
    request_body: Optional[Dict[str, Any]] = None
    responses: Optional[Dict[str, Any]] = None
    authentication: Optional[str] = None
    sample_request: Optional[str] = None
    sample_response: Optional[str] = None
    is_documented: bool = True
    is_deprecated: bool = False
    deprecation_notice: Optional[str] = None
    tags: Optional[List[str]] = None

    @field_validator("sample_request", "sample_response", mode="before")
    @classmethod
    def coerce_to_string(cls, v):
        """LLM sometimes returns dicts instead of JSON strings — auto-convert."""
        if isinstance(v, (dict, list)):
            return _json.dumps(v, indent=2)
        return v


class ServiceVersion(BaseModel):
    version: str
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
    artifact_type: ArtifactType
    raw_content: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ServiceDoc(BaseModel):
    service_id: str
    name: str
    version: str
    summary: Optional[str] = None
    description: Optional[str] = None
    base_url: Optional[str] = None
    endpoints: List[EndpointDoc] = []
    authentication_requirements: Optional[str] = None
    capabilities: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    generated_at: Optional[datetime] = None
    source_artifact: Optional[ArtifactType] = None


class ChangeEntry(BaseModel):
    change_type: str  # added | removed | modified | deprecated
    category: str     # endpoint | parameter | schema | auth | info
    path: Optional[str] = None
    description: str
    breaking: bool = False
    details: Optional[str] = None


class ChangeLog(BaseModel):
    service_id: str
    from_version: str
    to_version: str
    summary: str
    changes: List[ChangeEntry] = []
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    breaking_changes_count: int = 0
    total_changes: int = 0


class GapReport(BaseModel):
    service_id: str
    total_endpoints_in_traffic: int
    documented_endpoints: int
    undocumented_endpoints: List[Dict[str, str]] = []
    missing_doc_endpoints: List[str] = []
    generated_at: datetime = Field(default_factory=datetime.utcnow)


# --- Request / Response models ---

class IngestRequest(BaseModel):
    service_id: str
    service_name: str
    version: str
    artifact_type: ArtifactType
    content: str = Field(..., description="Raw content: JSON/YAML for OpenAPI, git URL for git, JSON array for logs")
    metadata: Optional[Dict[str, Any]] = None


class GenerateDocRequest(BaseModel):
    service_id: str
    version: Optional[str] = None
    regenerate: bool = False


class ExplainServiceRequest(BaseModel):
    service_id: str
    version: Optional[str] = None
    question: Optional[str] = None


class CompareServicesRequest(BaseModel):
    service_id_a: str
    version_a: Optional[str] = None
    service_id_b: str
    version_b: Optional[str] = None


class ChangeLogRequest(BaseModel):
    service_id: str
    from_version: str
    to_version: str


class PublishDocRequest(BaseModel):
    service_id: str
    version: Optional[str] = None
    destination: str = "portal"  # portal | registry | both


class ServiceSummary(BaseModel):
    service_id: str
    name: str
    latest_version: str
    endpoint_count: int
    has_documentation: bool
    last_updated: Optional[datetime] = None
    undocumented_count: int = 0


class ExplainResponse(BaseModel):
    service_id: str
    version: str
    explanation: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class CompareResponse(BaseModel):
    service_a: str
    service_b: str
    comparison: str
    similarities: List[str] = []
    differences: List[str] = []
    recommendation: Optional[str] = None
    generated_at: datetime = Field(default_factory=datetime.utcnow)
