from __future__ import annotations
import sys
import os
import traceback

try:
    import crypt
except ImportError:
    import types
    sys.modules["crypt"] = types.ModuleType("crypt")

try:
    from main import app
except Exception as err:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI()

    @app.get("/health")
    @app.get("/{full_path:path}")
    async def debug_catchall(full_path: str = ""):
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "import_error": str(err),
                "traceback": traceback.format_exc().splitlines(),
            },
        )
