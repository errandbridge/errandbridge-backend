import sys
import os
import traceback

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI()

modules = ["database"]

failed_mod = None
failed_err = None
failed_tb = None

for mod in modules:
    try:
        __import__(mod)
    except Exception as e:
        failed_mod = mod
        failed_err = str(e)
        failed_tb = traceback.format_exc()
        break

@app.get("/health")
def health():
    if failed_mod:
        return JSONResponse(status_code=500, content={"failed_module": failed_mod, "error": failed_err, "traceback": failed_tb})
    return {"status": "healthy", "modules_loaded": len(modules)}
