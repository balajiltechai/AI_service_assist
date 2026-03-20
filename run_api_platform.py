"""Entry point for the APIPlatform Mock API server.

Run from project root:
    python run_api_platform.py

Serves on http://localhost:8001
Docs at  http://localhost:8001/docs
"""
import sys
sys.path.insert(0, ".")

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "api_platform.server:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        reload_dirs=["api_platform"],
    )
