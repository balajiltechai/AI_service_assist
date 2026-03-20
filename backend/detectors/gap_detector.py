"""
Gap detector: compares traffic logs vs. registered/documented endpoints
to find undocumented endpoints and missing documentation.
"""
import re
from typing import List, Dict, Any, Set, Tuple

from backend.llm_client import call_llm


def _path_to_pattern(path: str) -> re.Pattern:
    """Convert a path template like /users/{id}/orders to a regex."""
    escaped = re.escape(path)
    pattern = re.sub(r'\\\{[^}]+\\\}', r'[^/]+', escaped)
    return re.compile(f"^{pattern}$")


def _match_traffic_to_doc(
    traffic_path: str,
    doc_paths: List[str]
) -> bool:
    """Check if a traffic path matches any documented path template."""
    # Direct match
    if traffic_path in doc_paths:
        return True
    # Template match
    for doc_path in doc_paths:
        if "{" in doc_path or ":" in doc_path:
            # Convert colon-style params to brace style
            normalized = re.sub(r':[a-zA-Z_][a-zA-Z0-9_]*', '{param}', doc_path)
            pattern = _path_to_pattern(normalized)
            if pattern.match(traffic_path):
                return True
    return False


def detect_gaps(
    traffic_endpoints: List[Dict[str, Any]],
    service_doc: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Compare traffic endpoints against documented endpoints.

    Returns:
      - undocumented: endpoints in traffic not in docs
      - missing_doc_endpoints: documented endpoints with no summary/description
      - gap_score: percentage of traffic covered by docs
    """
    # Build documented endpoint index: (method, path_pattern)
    doc_endpoints = service_doc.get("endpoints", [])
    doc_index: Dict[str, List[str]] = {}  # method -> list of paths
    for ep in doc_endpoints:
        method = ep.get("method", "GET").upper()
        path = ep.get("path", "/")
        doc_index.setdefault(method, []).append(path)

    undocumented = []
    for traffic_ep in traffic_endpoints:
        method = traffic_ep.get("method", "GET").upper()
        path = traffic_ep.get("path", "/")

        doc_paths_for_method = doc_index.get(method, [])
        if not _match_traffic_to_doc(path, doc_paths_for_method):
            undocumented.append({
                "method": method,
                "path": path,
                "hit_count": traffic_ep.get("hit_count", 0),
                "status_codes": traffic_ep.get("status_codes", []),
            })

    # Find documented endpoints missing description/summary
    missing_doc = []
    for ep in doc_endpoints:
        if not ep.get("summary") and not ep.get("description"):
            missing_doc.append(f"{ep.get('method', 'GET')} {ep.get('path', '/')}")

    total_traffic = len(traffic_endpoints)
    covered = total_traffic - len(undocumented)
    coverage_pct = round(covered / total_traffic * 100, 1) if total_traffic > 0 else 100.0

    return {
        "total_endpoints_in_traffic": total_traffic,
        "documented_endpoints": len(doc_endpoints),
        "covered_by_docs": covered,
        "documentation_coverage_pct": coverage_pct,
        "undocumented_endpoints": undocumented,
        "missing_doc_endpoints": missing_doc,
        "severity": _severity(coverage_pct, len(undocumented)),
    }


def _severity(coverage_pct: float, undoc_count: int) -> str:
    if coverage_pct >= 95 and undoc_count == 0:
        return "none"
    if coverage_pct >= 80:
        return "low"
    if coverage_pct >= 60:
        return "medium"
    return "high"


def generate_gap_recommendations(gap_report: Dict[str, Any], service_name: str) -> str:
    """Use LLM to generate actionable recommendations for closing documentation gaps."""
    system = (
        "You are a developer experience engineer. Help teams close API documentation gaps "
        "with clear, prioritized, actionable recommendations."
    )

    undoc = gap_report.get("undocumented_endpoints", [])
    missing = gap_report.get("missing_doc_endpoints", [])

    user = f"""Service: {service_name}
Documentation coverage: {gap_report.get('documentation_coverage_pct', 0)}%
Undocumented endpoints in traffic: {len(undoc)}
Documented but description-missing endpoints: {len(missing)}

Undocumented endpoints (by traffic volume):
{chr(10).join(f"- {e['method']} {e['path']} ({e['hit_count']} hits)" for e in undoc[:10])}

Endpoints missing descriptions:
{chr(10).join(f"- {e}" for e in missing[:10])}

Provide:
1. Priority order for which gaps to fix first (based on traffic volume and severity)
2. Specific action steps for each gap type
3. Estimated effort level (low/medium/high)
4. Long-term recommendations to prevent future gaps

Format as clear bullet points, developer-friendly."""

    return call_llm(system, user)
