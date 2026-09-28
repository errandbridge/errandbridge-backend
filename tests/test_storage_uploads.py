from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile

from app.routes import pilot_delivery
from app.services import storage


def test_local_storage_writes_to_the_configured_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setenv("STORAGE_DRIVER", "local")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))

    driver, path = storage.put_bytes("pilot-id.png", b"image", "image/png")

    assert driver == "local"
    assert path == str(tmp_path / "pilot-id.png")
    assert (tmp_path / "pilot-id.png").read_bytes() == b"image"


def test_serverless_local_storage_is_rejected_before_writing(monkeypatch, tmp_path):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("STORAGE_DRIVER", "local")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))

    with pytest.raises(storage.StorageConfigurationError, match="require S3"):
        storage.put_bytes("pilot-id.png", b"image", "image/png")

    assert not (tmp_path / "pilot-id.png").exists()


def test_missing_s3_bucket_returns_a_configuration_error(monkeypatch):
    monkeypatch.setenv("STORAGE_DRIVER", "s3")
    monkeypatch.delenv("S3_BUCKET", raising=False)

    with pytest.raises(storage.StorageConfigurationError, match="S3_BUCKET"):
        storage.put_bytes("pilot-id.png", b"image", "image/png")


def test_s3_storage_writes_document_with_a_private_object_key(monkeypatch):
    calls = []

    class FakeS3:
        def put_object(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setenv("STORAGE_DRIVER", "s3")
    monkeypatch.setenv("S3_BUCKET", "errandbridge-private-documents")
    monkeypatch.setenv("S3_PREFIX", "pilot-documents")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setattr(storage, "_s3_client", lambda _region: FakeS3())

    driver, key = storage.put_bytes("pilot-id.png", b"image", "image/png")

    assert (driver, key) == ("s3", "pilot-documents/pilot-id.png")
    assert calls == [{
        "Bucket": "errandbridge-private-documents",
        "Key": "pilot-documents/pilot-id.png",
        "Body": b"image",
        "ContentType": "image/png",
    }]


def test_s3_storage_errors_are_reported_without_an_internal_error(monkeypatch):
    class FailingS3:
        def put_object(self, **_kwargs):
            from botocore.exceptions import ClientError

            raise ClientError({"Error": {"Code": "AccessDenied"}}, "PutObject")

    monkeypatch.setenv("STORAGE_DRIVER", "s3")
    monkeypatch.setenv("S3_BUCKET", "errandbridge-private-documents")
    monkeypatch.setattr(storage, "_s3_client", lambda _region: FailingS3())

    with pytest.raises(storage.StorageWriteError, match="could not accept"):
        storage.put_bytes("pilot-id.png", b"image", "image/png")


@pytest.mark.asyncio
async def test_pilot_document_upload_returns_a_clear_service_error(monkeypatch):
    monkeypatch.setattr(
        pilot_delivery,
        "_get_current_user",
        AsyncMock(return_value=SimpleNamespace(id=uuid4())),
    )
    monkeypatch.setattr(
        pilot_delivery,
        "put_bytes",
        lambda **_kwargs: (_ for _ in ()).throw(
            storage.StorageConfigurationError("read-only")
        ),
    )
    file = UploadFile(filename="pilot-id.png", file=BytesIO(b"image"))

    with pytest.raises(HTTPException) as excinfo:
        await pilot_delivery.upload_pilot_document(
            document_type="driver_license",
            authorization="Bearer token",
            file=file,
            db=SimpleNamespace(),
        )

    assert excinfo.value.status_code == 503
    assert excinfo.value.detail == "Document uploads are temporarily unavailable. Please contact support."
