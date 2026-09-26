from __future__ import annotations
import sys
import os
import pathlib
import traceback

root_dir = str(pathlib.Path(__file__).parent.parent.resolve())
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

try:
    import crypt
except ImportError:
    import types
    sys.modules["crypt"] = types.ModuleType("crypt")

try:
    from main import app
except Exception as e:
    err_text = traceback.format_exc()
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI()

    @app.get("/health")
    @app.get("/{full_path:path}")
    def catchall(full_path: str = ""):
        return JSONResponse(status_code=200, content={"import_error": err_text})
