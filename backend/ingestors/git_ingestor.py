"""
Ingests Git repository data: recent commits, file structure, and version history.
"""
import json
import subprocess
from typing import Dict, Any, List, Optional
from pathlib import Path
import tempfile
import shutil


def _run(cmd: List[str], cwd: str) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=60)
    return result.stdout.strip()


def clone_repo(git_url: str) -> Optional[str]:
    """Clone a repo to a temp dir and return the path."""
    tmp = tempfile.mkdtemp(prefix="docu_git_")
    try:
        subprocess.run(
            ["git", "clone", "--depth", "50", git_url, tmp],
            capture_output=True, check=True, timeout=120
        )
        return tmp
    except subprocess.CalledProcessError:
        shutil.rmtree(tmp, ignore_errors=True)
        return None


def extract_git_data(repo_path: str) -> Dict[str, Any]:
    """Extract useful metadata from a local git repository."""
    # Recent commits
    log_raw = _run([
        "git", "log", "--oneline", "--max-count=50",
        "--format=%H|%an|%ae|%ad|%s", "--date=iso"
    ], repo_path)

    commits = []
    for line in log_raw.splitlines():
        parts = line.split("|", 4)
        if len(parts) == 5:
            commits.append({
                "hash": parts[0],
                "author": parts[1],
                "email": parts[2],
                "date": parts[3],
                "message": parts[4],
            })

    # Tags (versions)
    tags_raw = _run(["git", "tag", "--sort=-version:refname"], repo_path)
    tags = [t for t in tags_raw.splitlines() if t]

    # File structure (top-level + key files)
    files_raw = _run(["git", "ls-files"], repo_path)
    all_files = files_raw.splitlines()

    # Key files: README, changelog, openapi/swagger specs
    key_files = []
    for f in all_files:
        lower = f.lower()
        if any(k in lower for k in ["readme", "changelog", "openapi", "swagger", "api"]):
            key_files.append(f)

    # Try to read README
    readme_content = None
    for f in all_files:
        if f.lower().startswith("readme"):
            try:
                readme_content = Path(repo_path, f).read_text(errors="replace")[:3000]
                break
            except Exception:
                pass

    # Try to find OpenAPI spec in repo
    openapi_content = None
    for f in all_files:
        lower = f.lower()
        if any(k in lower for k in ["openapi", "swagger"]) and any(
            f.endswith(ext) for ext in [".json", ".yaml", ".yml"]
        ):
            try:
                openapi_content = Path(repo_path, f).read_text(errors="replace")
                break
            except Exception:
                pass

    # Contributors
    contributors_raw = _run([
        "git", "shortlog", "-sn", "--no-merges"
    ], repo_path)
    contributors = []
    for line in contributors_raw.splitlines():
        parts = line.strip().split("\t", 1)
        if len(parts) == 2:
            contributors.append({"commits": int(parts[0].strip()), "name": parts[1]})

    # Branch info
    current_branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo_path)

    return {
        "commits": commits,
        "tags": tags,
        "all_files": all_files[:200],
        "key_files": key_files,
        "readme": readme_content,
        "openapi_in_repo": openapi_content,
        "contributors": contributors[:10],
        "current_branch": current_branch,
        "total_files": len(all_files),
    }


def extract_version_changes(repo_path: str, from_tag: str, to_tag: str) -> Dict[str, Any]:
    """Extract commit messages and file changes between two tags/versions."""
    log_raw = _run([
        "git", "log", f"{from_tag}..{to_tag}",
        "--format=%H|%an|%ad|%s", "--date=iso"
    ], repo_path)

    commits = []
    for line in log_raw.splitlines():
        parts = line.split("|", 3)
        if len(parts) == 4:
            commits.append({
                "hash": parts[0],
                "author": parts[1],
                "date": parts[2],
                "message": parts[3],
            })

    diff_stat = _run([
        "git", "diff", "--stat", from_tag, to_tag
    ], repo_path)

    changed_files = _run([
        "git", "diff", "--name-only", from_tag, to_tag
    ], repo_path).splitlines()

    return {
        "from_tag": from_tag,
        "to_tag": to_tag,
        "commits": commits,
        "diff_stat": diff_stat,
        "changed_files": changed_files,
    }


def ingest_from_url(git_url: str) -> Dict[str, Any]:
    """Clone a repo and return structured data. Cleans up after."""
    repo_path = clone_repo(git_url)
    if not repo_path:
        return {"error": f"Failed to clone {git_url}", "commits": [], "tags": []}
    try:
        data = extract_git_data(repo_path)
        data["source_url"] = git_url
        return data
    finally:
        shutil.rmtree(repo_path, ignore_errors=True)
