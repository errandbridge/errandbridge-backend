import sys
import os
import traceback

# Ensure root directory is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from fastapi import FastAPI
from fastapi.responses import JSONResponse

try:
    from main import app
except Exception as e:
    tb = traceback.format_exc()
    app = FastAPI()

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
    async def catch_all(path: str, request=None):
        return JSONResponse(
            status_code=500,
            content={
                "error": "Failed to import main.py during startup",
                "exception": str(e),
                "traceback": tb,
            },
        )
