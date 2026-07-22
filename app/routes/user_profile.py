"""User profile image routes.

Client users previously stored profile images in localStorage only. This router
adds a server-backed profile image upload/remove endpoint so profile images
persist across sessions and devices.

- PUT /v1/users/profile-image
  - profile_image=<file> uploads and stores /uploads/profiles/<filename>
  - remove_profile_image=true clears the stored profile_image_url

Images are stored under <backend>/uploads/profiles.
"""

from __future__ import annotations

from datetime import datetime
import os
import logging
import sys
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

# Add parent directory to path (repo convention used in other route modules)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from auth import decode_access_token
from database import get_db
from models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/users", tags=["user-profile"])

# Upload directory for profile images
UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "uploads",
    "profiles",
)
os.makedirs(UPLOAD_DIR, exist_ok=True)

_MAX_IMAGE_BYTES = 5 * 1024 * 1024


def _extract_bearer(auth_header: Optional[str]) -> Optional[str]:
    if not auth_header:
        return None
    parts = auth_header.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


async def _get_current_user(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user


@router.put("/profile-image")
async def update_profile_image(
    remove_profile_image: bool = Form(default=False),
    profile_image: UploadFile | None = File(default=None),
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Upload or remove the current user's profile image."""

    user = await _get_current_user(authorization, db)

    if remove_profile_image:
        try:
            setattr(user, "profile_image_url", None)
            await db.commit()
            return {"ok": True, "profile_image_url": None}
        except Exception as e:
            logger.error(f"Error removing profile image: {e}")
            raise HTTPException(status_code=500, detail="Failed to remove profile image")

    if not profile_image:
        raise HTTPException(status_code=400, detail="Missing profile_image")

    # Validate file type
    if not (profile_image.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="Invalid image file")

    content = await profile_image.read()
    if len(content) > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Image too large (max 5MB)")

    file_ext = os.path.splitext(profile_image.filename or "")[1]
    # Keep extension sane; fall back to .jpg for unknown.
    if not file_ext or len(file_ext) > 10:
        file_ext = ".jpg"

    file_name = f"user_{user.id}_{datetime.now().timestamp()}{file_ext}"
    file_path = os.path.join(UPLOAD_DIR, file_name)

    try:
        with open(file_path, "wb") as f:
            f.write(content)

        profile_image_url = f"/uploads/profiles/{file_name}"
        setattr(user, "profile_image_url", profile_image_url)
        await db.commit()

        return {"ok": True, "profile_image_url": profile_image_url}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving profile image: {e}")
        raise HTTPException(status_code=500, detail="Failed to save profile image")
