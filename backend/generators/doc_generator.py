"""
LLM-powered documentation generator using Ollama (local LLM).
Generates: service summaries, endpoint docs, capability descriptions,
auth explanations, sample request/response, deprecation notices.
"""
import json
from typing import Dict, Any, List, Optional

from backend.llm_client import call_llm, stream_llm_fast
from backend.models.schemas import ServiceDoc, EndpointDoc


# ─── Service-level generation ────────────────────────────────────────────────

def generate_service_summary(
    name: str,
    version: str,
    raw_spec: str,
    artifact_type: str,
    extra_context: Optional[str] = None
) -> Dict[str, Any]:
    """Generate a full service summary from raw artifact content."""
    system = (
        "You are a senior API documentation engineer and developer advocate. "
        "Your job is to generate thorough, accurate, developer-friendly documentation "
        "from service artifacts. Write as if for an official developer portal — "
        "clear, precise, rich with examples and practical guidance. Always return valid JSON."
    )

    context_block = f"\n\nAdditional context:\n{extra_context}" if extra_context else ""
    spec_preview = raw_spec[:8000]

    user = f"""Analyze this service artifact and generate comprehensive documentation.

Service Name: {name}
Version: {version}
Artifact Type: {artifact_type}

Artifact Content:
{spec_preview}
{context_block}

Return a JSON object with these fields:
{{
  "summary": "2-3 sentence executive summary covering what the service does, its primary value, and who it serves",
  "description": "5-7 paragraph detailed description covering: (1) purpose and business context, (2) core capabilities and what problems it solves, (3) key use cases with concrete examples, (4) how it fits into a typical architecture, (5) versioning and stability notes, (6) performance and scalability characteristics if inferable, (7) any important constraints or prerequisites",
  "capabilities": ["comprehensive list of all key capabilities — be specific, e.g. 'Idempotent charge creation via idempotency keys' not just 'Payments'"],
  "authentication_requirements": "Thorough explanation of all auth methods supported: scheme type (Bearer JWT, API key, OAuth2, etc.), where to pass credentials, required scopes or permissions per operation, token expiry and refresh guidance, and a concrete example header",
  "target_consumers": "Detailed description of who should use this service: team types, use cases they cover, skill level assumed",
  "key_concepts": ["domain concepts a developer must understand before using this service — include brief definitions"],
  "notes": "Important gotchas, known limitations, deprecation warnings, rate limits, pagination patterns, error handling conventions, and any non-obvious behaviours developers frequently encounter"
}}"""

    raw = call_llm(system, user)
    # Extract JSON from response
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        return json.loads(raw[start:end])
    except (json.JSONDecodeError, ValueError):
        return {
            "summary": raw[:300],
            "description": raw,
            "capabilities": [],
            "authentication_requirements": "See service spec for details.",
            "target_consumers": "Developers",
            "key_concepts": [],
            "notes": "",
        }


# ─── Endpoint-level generation ────────────────────────────────────────────────

def generate_endpoint_docs(
    service_name: str,
    endpoints: List[EndpointDoc],
    service_context: str = ""
) -> List[EndpointDoc]:
    """Enrich endpoint docs with LLM-generated descriptions, samples, auth info."""
    system = (
        "You are an expert API documentation engineer. "
        "Generate clear developer documentation for API endpoints. "
        "Always return a valid JSON array."
    )

    # Process in batches to manage token usage
    batch_size = 10
    enriched = []

    for i in range(0, len(endpoints), batch_size):
        batch = endpoints[i:i + batch_size]
        endpoints_data = []
        for ep in batch:
            endpoints_data.append({
                "method": ep.method,
                "path": ep.path,
                "summary": ep.summary,
                "description": ep.description,
                "parameters": ep.parameters,
                "authentication": ep.authentication,
                "is_deprecated": ep.is_deprecated,
                "tags": ep.tags,
            })

        user = f"""For the service "{service_name}", generate detailed developer documentation for these API endpoints.
{f"Service context: {service_context[:600]}" if service_context else ""}

Endpoints:
{json.dumps(endpoints_data, indent=2)}

Return a JSON array where each item has:
{{
  "method": "same as input",
  "path": "same as input",
  "summary": "clear 1-sentence summary stating exactly what this endpoint does",
  "description": "2-3 paragraph description covering: what it does and when to use it, key behaviours (idempotency, async vs sync, side effects), common patterns and real-world use cases with examples",
  "authentication": "exact auth requirement: scheme, required scopes/permissions, and example Authorization header value",
  "sample_request": {{"realistic": "JSON request body with representative field values and comments where helpful — null for GET/DELETE without body"}},
  "sample_response": {{"realistic": "JSON success response showing all important fields with representative values"}},
  "deprecation_notice": "migration guidance and replacement endpoint if deprecated, else null",
  "usage_notes": "important practical notes: rate limits, pagination strategy, error codes to handle, retry behaviour, ordering guarantees, partial failure handling"
}}"""

        raw = call_llm(system, user)
        try:
            start = raw.find("[")
            end = raw.rfind("]") + 1
            batch_results = json.loads(raw[start:end])
        except (json.JSONDecodeError, ValueError):
            batch_results = [{}] * len(batch)

        for ep, result in zip(batch, batch_results):
            ep.summary = result.get("summary") or ep.summary
            ep.description = result.get("description") or ep.description
            ep.authentication = result.get("authentication") or ep.authentication
            # LLM sometimes returns dicts instead of strings — serialize to JSON string
            sr = result.get("sample_request")
            ep.sample_request = json.dumps(sr, indent=2) if isinstance(sr, dict) else (sr or ep.sample_request)
            srp = result.get("sample_response")
            ep.sample_response = json.dumps(srp, indent=2) if isinstance(srp, dict) else (srp or ep.sample_response)
            ep.deprecation_notice = result.get("deprecation_notice") or ep.deprecation_notice
            enriched.append(ep)

    return enriched


# ─── Explain service feature ──────────────────────────────────────────────────

async def explain_service(
    service_doc: Dict[str, Any],
    question: Optional[str] = None
):
    """Stream a natural language explanation of a service, optionally answering a question."""
    system = (
        "You are a knowledgeable developer advocate who explains services clearly. "
        "Tailor your explanation for a developer audience. Be helpful and thorough."
    )

    # Minimal input — no heavy endpoint details to keep latency low
    doc_summary = (
        f"Service: {service_doc.get('name')} {service_doc.get('version')}\n"
        f"Summary: {service_doc.get('summary')}\n"
        f"Description: {str(service_doc.get('description', ''))[:400]}\n"
        f"Capabilities: {', '.join((service_doc.get('capabilities') or [])[:8])}\n"
        f"Auth: {str(service_doc.get('authentication_requirements', ''))[:300]}\n"
        f"Key endpoints: {', '.join((e.get('method', '') + ' ' + e.get('path', '')) for e in service_doc.get('endpoints', [])[:10])}"
    )

    if question:
        user = f"""Here is documentation for the service "{service_doc.get('name')}":

{doc_summary}

Developer question: {question}

Answer the question thoroughly based on the service documentation. Include examples where helpful.
If the answer isn't in the docs, say so and explain what you do know."""
    else:
        user = f"""Here is documentation for the service "{service_doc.get('name')}":

{doc_summary}

Provide a comprehensive explanation covering:
1. What this service does (plain language)
2. When and why developers should use it
3. Key capabilities and features
4. How authentication works
5. Most important endpoints and their use cases
6. Any gotchas or important notes
7. Quick-start guidance

Make it developer-friendly and practical."""

    async for chunk in stream_llm_fast(system, user, max_tokens=1500):
        yield chunk


# ─── Compare services feature ──────────────────────────────────────────────────

async def compare_services(
    service_a: Dict[str, Any],
    service_b: Dict[str, Any],
):
    """Stream a comparison of two services as SSE-compatible text chunks."""
    system = (
        "You are an expert API architect who helps developers choose between services. "
        "Provide objective, detailed comparisons. Return valid JSON only, no markdown."
    )

    def mini(doc: Dict) -> str:
        caps = ", ".join((doc.get("capabilities") or [])[:7])
        endpoints = ", ".join(
            f"{e.get('method')} {e.get('path')}"
            for e in doc.get("endpoints", [])[:8]
        )
        return (
            f"name={doc.get('name')} version={doc.get('version')}\n"
            f"summary={str(doc.get('summary', ''))[:200]}\n"
            f"capabilities={caps}\n"
            f"auth={str(doc.get('authentication_requirements', ''))[:150]}\n"
            f"endpoints={endpoints}"
        )

    user = f"""Compare these two services and help a developer choose the right one.

Service A:
{mini(service_a)}

Service B:
{mini(service_b)}

Return a JSON object with:
{{
  "comparison_narrative": "3-4 paragraph narrative comparison covering purpose, capabilities, and use cases",
  "similarities": ["list of key similarities"],
  "differences": ["list of key differences"],
  "service_a_strengths": ["strengths of service A"],
  "service_b_strengths": ["strengths of service B"],
  "use_service_a_when": "detailed guidance on when to choose service A",
  "use_service_b_when": "detailed guidance on when to choose service B",
  "recommendation": "overall recommendation with reasoning"
}}"""

    async for chunk in stream_llm_fast(system, user, max_tokens=1500):
        yield chunk
