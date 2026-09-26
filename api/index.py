import sys
import os
import traceback

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

_main_app = None
_import_error = None

def get_main_app():
    global _main_app, _import_error
    if _main_app is None and _import_error is None:
        try:
            from main import app as loaded_app
            _main_app = loaded_app
        except Exception as e:
            _import_error = traceback.format_exc()
    return _main_app

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def handle_request(request: Request, path: str = ""):
    main_instance = get_main_app()
    if main_instance is not None:
        return await main_instance(request.scope, request.receive, request._send)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Failed to import main.py",
            "traceback": _import_error,
        },
    )
