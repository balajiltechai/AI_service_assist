"""
Ingests HTTP access logs / distributed traces and extracts endpoint traffic patterns.
Supports JSON-array format and Common Log Format (CLF).
"""
import re
import json
from typing import List, Dict, Any
from collections import defaultdict


# Common Log Format pattern
CLF_PATTERN = re.compile(
    r'(?P<host>\S+)\s+\S+\s+\S+\s+\[(?P<time>[^\]]+)\]\s+'
    r'"(?P<method>\S+)\s+(?P<path>\S+)\s+\S+"\s+'
    r'(?P<status>\d{3})\s+(?P<bytes>\S+)'
)


def _normalize_path(path: str) -> str:
    """Replace path segments that look like IDs with {id} placeholder."""
    path = path.split("?")[0]  # strip query string
    parts = path.split("/")
    normalized = []
    for part in parts:
        if re.match(r'^[0-9a-f\-]{8,}$', part, re.IGNORECASE):
            normalized.append("{id}")
        elif part.isdigit():
            normalized.append("{id}")
        else:
            normalized.append(part)
    return "/".join(normalized)


def parse_json_logs(content: str) -> List[Dict[str, Any]]:
    """Parse JSON array of log entries. Each entry needs method + path."""
    try:
        entries = json.loads(content)
        if not isinstance(entries, list):
            entries = [entries]
        result = []
        for entry in entries:
            method = entry.get("method", entry.get("http_method", "GET")).upper()
            path = (
                entry.get("path")
                or entry.get("url")
                or entry.get("request_uri")
                or "/"
            )
            status = entry.get("status", entry.get("status_code", 200))
            result.append({
                "method": method,
                "path": _normalize_path(path),
                "status": int(status),
                "timestamp": entry.get("timestamp") or entry.get("time", ""),
            })
        return result
    except (json.JSONDecodeError, ValueError):
        return []


def parse_clf_logs(content: str) -> List[Dict[str, Any]]:
    """Parse Common Log Format access log lines."""
    result = []
    for line in content.splitlines():
        m = CLF_PATTERN.match(line.strip())
        if m:
            result.append({
                "method": m.group("method").upper(),
                "path": _normalize_path(m.group("path")),
                "status": int(m.group("status")),
                "timestamp": m.group("time"),
            })
    return result


def aggregate_traffic(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aggregate log entries into unique endpoint hit counts."""
    counter: Dict[tuple, Dict] = defaultdict(lambda: {"hit_count": 0, "statuses": []})

    for entry in entries:
        key = (entry["method"], entry["path"])
        counter[key]["hit_count"] += 1
        counter[key]["statuses"].append(entry.get("status", 200))

    result = []
    for (method, path), data in counter.items():
        statuses = data["statuses"]
        result.append({
            "method": method,
            "path": path,
            "hit_count": data["hit_count"],
            "success_rate": round(
                sum(1 for s in statuses if 200 <= s < 400) / len(statuses) * 100, 1
            ),
            "status_codes": list(set(statuses)),
        })

    return sorted(result, key=lambda x: x["hit_count"], reverse=True)


def ingest_logs(content: str) -> Dict[str, Any]:
    """
    Auto-detect log format and return aggregated traffic data.
    Returns dict with 'endpoints' list and 'total_requests'.
    """
    content = content.strip()

    # Try JSON first
    entries = parse_json_logs(content)
    if not entries:
        # Fall back to CLF
        entries = parse_clf_logs(content)

    if not entries:
        return {
            "endpoints": [],
            "total_requests": 0,
            "error": "Could not parse log content. Provide JSON array or CLF format.",
        }

    aggregated = aggregate_traffic(entries)
    return {
        "endpoints": aggregated,
        "total_requests": len(entries),
        "unique_endpoints": len(aggregated),
    }
