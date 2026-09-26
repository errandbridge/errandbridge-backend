from __future__ import annotations
import sys
import os
import pathlib
import traceback

# Ensure root repository directory is on sys.path so modules like main, database, models can be imported
root_dir = str(pathlib.Path(__file__).parent.parent.resolve())
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

try:
    import crypt
except ImportError:
    import types
    sys.modules["crypt"] = types.ModuleType("crypt")

# Top-level assignment so @vercel/python build parser finds the entrypoint
app = None

try:
    from main import app as _main_app
    app = _main_app
except Exception as err:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    _fallback_app = FastAPI()

    @_fallback_app.get("/health")
    @_fallback_app.get("/{full_path:path}")
    async def debug_catchall(full_path: str = ""):
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "import_error": str(err),
                "traceback": traceback.format_exc().splitlines(),
            },
        )

    app = _fallback_app

handler = app
application = app
