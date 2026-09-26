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
_import_tb = None

try:
    from main import app as _main_app
except Exception as e:
    _import_error = str(e)
    _import_tb = traceback.format_exc()

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def handle_request(request: Request, path: str = ""):
    if _main_app is not None:
        return await _main_app(request.scope, request.receive, request._send)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Failed to load main application",
            "exception": _import_error,
            "traceback": _import_tb,
        },
    )
