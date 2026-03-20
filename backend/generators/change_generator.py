"""
LLM-powered change log generator using Ollama (local LLM).
Compares two versions of a service and produces structured, human-readable change logs.
"""
import json
from typing import Dict, Any, List, Optional

from backend.llm_client import call_llm
from backend.models.schemas import ChangeLog, ChangeEntry


def _endpoint_set(doc: Dict) -> Dict[str, Dict]:
    """Build a dict of method+path -> endpoint data from a service doc."""
    result = {}
    for ep in doc.get("endpoints", []):
        key = f"{ep.get('method', 'GET').upper()} {ep.get('path', '/')}"
        result[key] = ep
    return result


def diff_endpoint_sets(doc_old: Dict, doc_new: Dict) -> Dict[str, Any]:
    """Structurally diff two service docs to find added/removed/changed endpoints."""
    old_eps = _endpoint_set(doc_old)
    new_eps = _endpoint_set(doc_new)

    old_keys = set(old_eps.keys())
    new_keys = set(new_eps.keys())

    added = list(new_keys - old_keys)
    removed = list(old_keys - new_keys)
    potentially_modified = list(old_keys & new_keys)

    modified = []
    for key in potentially_modified:
        old_ep = old_eps[key]
        new_ep = new_eps[key]
        changes = []
        # Check summary, description, auth, deprecated status
        if old_ep.get("summary") != new_ep.get("summary"):
            changes.append("summary changed")
        if old_ep.get("description") != new_ep.get("description"):
            changes.append("description changed")
        if old_ep.get("authentication") != new_ep.get("authentication"):
            changes.append("authentication changed")
        if not old_ep.get("is_deprecated") and new_ep.get("is_deprecated"):
            changes.append("endpoint deprecated")
        if old_ep.get("parameters") != new_ep.get("parameters"):
            changes.append("parameters changed")
        if old_ep.get("request_body") != new_ep.get("request_body"):
            changes.append("request body changed")
        if old_ep.get("responses") != new_ep.get("responses"):
            changes.append("responses changed")
        if changes:
            modified.append({"endpoint": key, "changes": changes})

    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "deprecated": [
            k for k in potentially_modified
            if not old_eps[k].get("is_deprecated") and new_eps[k].get("is_deprecated")
        ],
    }


def generate_change_log(
    service_id: str,
    service_name: str,
    from_version: str,
    to_version: str,
    doc_old: Dict[str, Any],
    doc_new: Dict[str, Any],
    git_data: Optional[Dict] = None,
) -> ChangeLog:
    """Generate a structured change log between two versions using LLM."""

    structural_diff = diff_endpoint_sets(doc_old, doc_new)

    system = (
        "You are a senior API change analyst. Generate detailed, accurate change logs "
        "that help developers understand what changed between API versions. "
        "Clearly flag breaking changes. Return valid JSON."
    )

    git_context = ""
    if git_data and git_data.get("commits"):
        commits = git_data["commits"][:20]
        git_context = f"\n\nGit commits between versions:\n" + "\n".join(
            f"- {c.get('message', '')}" for c in commits
        )

    user = f"""Generate a change log for service "{service_name}" from version {from_version} to {to_version}.

Structural diff:
- Added endpoints: {structural_diff['added']}
- Removed endpoints: {structural_diff['removed']}
- Modified endpoints: {json.dumps(structural_diff['modified'], indent=2)}
- Deprecated endpoints: {structural_diff['deprecated']}

Old version summary: {doc_old.get('summary', 'N/A')}
New version summary: {doc_new.get('summary', 'N/A')}

Old auth: {doc_old.get('authentication_requirements', 'N/A')}
New auth: {doc_new.get('authentication_requirements', 'N/A')}
{git_context}

Return a JSON object with:
{{
  "summary": "2-3 sentence executive summary of what changed",
  "changes": [
    {{
      "change_type": "added|removed|modified|deprecated",
      "category": "endpoint|parameter|schema|auth|info",
      "path": "affected endpoint path or null",
      "description": "clear description of the change",
      "breaking": true/false,
      "details": "additional details, migration steps if breaking"
    }}
  ]
}}

For each structural change found, create a change entry.
Mark breaking=true for: removed endpoints, auth changes, removed required parameters, response schema changes."""

    raw = call_llm(system, user)
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        result = json.loads(raw[start:end])
    except (json.JSONDecodeError, ValueError):
        result = {"summary": raw[:300], "changes": []}

    changes = []
    for c in result.get("changes", []):
        changes.append(ChangeEntry(
            change_type=c.get("change_type", "modified"),
            category=c.get("category", "endpoint"),
            path=c.get("path"),
            description=c.get("description", ""),
            breaking=c.get("breaking", False),
            details=c.get("details"),
        ))

    breaking_count = sum(1 for c in changes if c.breaking)

    return ChangeLog(
        service_id=service_id,
        from_version=from_version,
        to_version=to_version,
        summary=result.get("summary", ""),
        changes=changes,
        breaking_changes_count=breaking_count,
        total_changes=len(changes),
    )


def generate_deprecation_notice(
    service_name: str,
    endpoint_method: str,
    endpoint_path: str,
    replacement: Optional[str] = None,
    sunset_date: Optional[str] = None,
) -> str:
    """Generate a clear deprecation notice for an endpoint."""
    system = "You are a technical writer generating clear deprecation notices for API endpoints."

    user = f"""Generate a deprecation notice for:

Service: {service_name}
Endpoint: {endpoint_method} {endpoint_path}
Replacement endpoint: {replacement or "None provided"}
Sunset date: {sunset_date or "Not announced"}

Write a clear, helpful deprecation notice that:
1. States the endpoint is deprecated
2. Explains when it will be removed (if known)
3. Provides migration path to replacement (if available)
4. Includes any warnings about impact
Keep it under 150 words."""

    return call_llm(system, user)
