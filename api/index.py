from fastapi import FastAPI

app = FastAPI()

@app.get("/")
@app.get("/health")
@app.get("/{full_path:path}")
def health(full_path: str = ""):
    return {"status": "healthy", "minimal": True, "path": full_path}
