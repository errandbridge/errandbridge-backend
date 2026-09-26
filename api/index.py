import sys
import os
import traceback

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from fastapi import FastAPI
from fastapi.responses import JSONResponse

import_error = None
import_tb = None

try:
    from main import app
except Exception as e:
    import_error = str(e)
    import_tb = traceback.format_exc()

    app = FastAPI()

    @app.get("/health")
    def health_fallback():
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error": import_error,
                "traceback": import_tb,
            }
        )

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
    async def catch_all(path: str):
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error": import_error,
                "traceback": import_tb,
            }
        )
