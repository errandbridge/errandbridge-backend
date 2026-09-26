from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.get("/{path:path}")
def catch_all(path: str):
    return {"status": "healthy", "path": path}
