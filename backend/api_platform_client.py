"""
Client for the APIPlatform API.

All service registry data (services, specs, versions, traffic) comes from here
instead of from SQLite.
"""
import httpx
from typing import Optional, List, Dict, Any

from backend.config import get_settings


def _base() -> str:
    return get_settings().api_platform_url.rstrip("/")


async def list_services() -> List[Dict]:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{_base()}/services")
        r.raise_for_status()
        return r.json()["services"]


async def get_service(service_id: str) -> Optional[Dict]:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{_base()}/services/{service_id}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()


async def register_service(
    service_id: str,
    name: str,
    version: str,
    description: Optional[str] = None,
    base_url: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> Dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{_base()}/services", json={
            "service_id": service_id,
            "name": name,
            "version": version,
            "description": description,
            "base_url": base_url,
            "tags": tags or [],
        })
        r.raise_for_status()
        return r.json()


async def get_versions(service_id: str) -> List[str]:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{_base()}/services/{service_id}/versions")
        if r.status_code == 404:
            return []
        r.raise_for_status()
        return r.json()["versions"]


async def get_spec(service_id: str, version: Optional[str] = None) -> Optional[Dict]:
    """Returns dict with keys: service_id, version, content, artifact_type"""
    async with httpx.AsyncClient() as client:
        if version:
            url = f"{_base()}/services/{service_id}/spec/{version}"
        else:
            url = f"{_base()}/services/{service_id}/spec"
        r = await client.get(url)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()


async def upload_spec(
    service_id: str,
    version: str,
    content: str,
    artifact_type: str = "openapi",
) -> Dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{_base()}/services/{service_id}/spec", json={
            "version": version,
            "content": content,
            "artifact_type": artifact_type,
        })
        r.raise_for_status()
        return r.json()


async def get_traffic(service_id: str) -> List[Dict]:
    """Returns list of {method, path, hit_count} entries."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{_base()}/services/{service_id}/traffic")
        if r.status_code == 404:
            return []
        r.raise_for_status()
        return r.json()["entries"]


async def get_endpoints(service_id: str) -> List[Dict]:
    """Returns list of {method, path, summary} for a service's latest spec."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{_base()}/services/{service_id}/endpoints")
        if r.status_code == 404:
            return []
        r.raise_for_status()
        return r.json().get("endpoints", [])


async def add_traffic(service_id: str, entries: List[Dict[str, Any]]) -> Dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{_base()}/services/{service_id}/traffic",
            json=entries,
        )
        r.raise_for_status()
        return r.json()
