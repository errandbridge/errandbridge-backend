import os
from pathlib import Path

from fastapi.testclient import TestClient


def test_profile_image_public_route_serves_file():
    # Import lazily so the route is registered on module import.
    import main

    client = TestClient(main.app)

    upload_dir = getattr(main, "PROFILE_UPLOAD_DIR", None)
    assert upload_dir is not None

    upload_dir = Path(str(upload_dir))
    upload_dir.mkdir(parents=True, exist_ok=True)

    filename = "pytest_profile_test.png"
    path = upload_dir / filename

    # Minimal PNG signature + dummy bytes.
    payload = b"\x89PNG\r\n\x1a\n" + b"0" * 64

    try:
        path.write_bytes(payload)
        res = client.get(f"/uploads/profiles/{filename}")
        assert res.status_code == 200
        assert res.content.startswith(b"\x89PNG")
        # Content type is best-effort; allow either explicit image type or octet-stream.
        assert res.headers.get("content-type", "").startswith(("image/", "application/octet-stream"))
    finally:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


def test_profile_image_public_route_rejects_path_traversal():
    import main

    client = TestClient(main.app)

    res = client.get("/uploads/profiles/../secrets.txt")
    assert res.status_code in (400, 404)
