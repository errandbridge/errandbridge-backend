"""
Pilot Profile Settings Routes
Handles pilot profile updates: personal info, address, vehicle details
"""

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    Body,
    Header,
    File,
    UploadFile,
    Form,
    Query,
)
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import Optional
from datetime import datetime
import os
import logging
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from models import User
from database import get_db
from app.dto import (
    PilotProfileUpdateResponse,
    PilotChangePasswordResponse,
    PilotProfileResponse,
    PilotStatsResponse,
    PilotAvailabilityResponse,
)
from auth import decode_access_token
from app.pilot_dispatch import (
    ADMIN_DISPATCH_ENABLED,
    serialize_pilot_dispatch_state,
    set_pilot_availability,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pilots", tags=["pilot-profile"])

# Upload directory for profile images.
# Keep this aligned with the backend's global UPLOAD_DIR (used elsewhere for local storage)
# so the public /uploads/profiles/<filename> endpoint can serve the saved files.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_UPLOAD_DIR = _BACKEND_ROOT / "uploads"
BASE_UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(_DEFAULT_UPLOAD_DIR)))
PROFILE_UPLOAD_DIR = BASE_UPLOAD_DIR / "profiles"
try:
    PROFILE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
except OSError as e:
    logger.warning(
        f"Could not create profile upload directory (serverless environment?): {e}"
    )


class AddressUpdate(BaseModel):
    street_address: Optional[str] = None
    city: str
    state_province: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None


class PilotAvailabilityUpdate(BaseModel):
    availability: str


class VehicleUpdate(BaseModel):
    vehicle_type: Optional[str] = None
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_year: Optional[int] = None
    license_plate: Optional[str] = None
    insurance_provider: Optional[str] = None
    insurance_expiry: Optional[str] = None


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


def _normalize_vehicle_type(value: Optional[str]) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _pilot_has_bike(user: User) -> bool:
    vehicle_type = _normalize_vehicle_type(getattr(user, "vehicle_type", None))
    return bool(
        getattr(user, "hasBike", False)
        or getattr(user, "has_bike", False)
        or vehicle_type
        in {"bike", "bike_support", "bicycle", "motorbike", "motorcycle", "scooter"}
    )


def _pilot_has_car(user: User) -> bool:
    vehicle_type = _normalize_vehicle_type(getattr(user, "vehicle_type", None))
    return bool(
        getattr(user, "hasCar", False)
        or getattr(user, "has_car", False)
        or vehicle_type in {"car", "saloon", "sedan", "suv", "van", "truck"}
    )


def _pilot_cross_city_available(user: User) -> bool:
    return bool(
        getattr(user, "crossCityAvailable", False)
        or getattr(user, "cross_city_available", False)
    )


def _pilot_service_radius_km(user: User) -> Optional[float]:
    raw = (
        getattr(user, "serviceRadius", None)
        or getattr(user, "service_radius_km", None)
        or getattr(user, "service_radius", None)
    )
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _serialize_profile(user: User) -> dict:
    dispatch_state = serialize_pilot_dispatch_state(user)
    city = getattr(user, "city", None)
    state_province = getattr(user, "state_province", None)
    insurance_expiry = getattr(user, "insurance_expiry", None)
    return {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone": user.phone,
        "is_email_verified": bool(user.is_email_verified),
        "must_change_password": bool(getattr(user, "must_change_password", False)),
        "id_verification_status": getattr(user, "id_verification_status", "pending"),
        "address_verification_status": getattr(
            user, "address_verification_status", "pending"
        ),
        "date_of_birth": user.date_of_birth.isoformat() if user.date_of_birth else None,
        "profile_image_url": getattr(user, "profile_image_url", None),
        "street_address": getattr(user, "street_address", None),
        "city": city,
        "state_province": state_province,
        "postal_code": getattr(user, "postal_code", None),
        "country": getattr(user, "country", None),
        "vehicle_type": getattr(user, "vehicle_type", None),
        "vehicle_make": getattr(user, "vehicle_make", None),
        "vehicle_model": getattr(user, "vehicle_model", None),
        "vehicle_year": getattr(user, "vehicle_year", None),
        "license_plate": getattr(user, "license_plate", None),
        "insurance_provider": getattr(user, "insurance_provider", None),
        "insurance_expiry": insurance_expiry.isoformat() if insurance_expiry else None,
        "has_bike": _pilot_has_bike(user),
        "has_car": _pilot_has_car(user),
        "cross_city_available": _pilot_cross_city_available(user),
        "service_radius_km": _pilot_service_radius_km(user),
        "service_area_text": city or state_province,
        **dispatch_state,
    }


def _extract_bearer(auth_header: Optional[str]) -> Optional[str]:
    """Extract bearer token from Authorization header"""
    if not auth_header:
        return None
    parts = auth_header.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


async def _get_current_user(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Get current authenticated user"""
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token"
        )

    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )

    if not getattr(user, "is_pilot", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Pilot access required"
        )

    return user


@router.get("/profile", response_model=PilotProfileResponse, operation_id="getPilotProfile", summary="Get pilot profile", description="Retrieve detailed pilot profile including vehicle and availability info.")
async def get_profile(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Get current pilot profile"""
    try:
        user = await _get_current_user(authorization, db)
        return _serialize_profile(user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting profile: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get profile",
        )


@router.put("/availability", response_model=PilotAvailabilityResponse, operation_id="updatePilotAvailability", summary="Update pilot availability", description="Toggle pilot status between online, offline, or busy.")
async def update_availability(
    payload: PilotAvailabilityUpdate = Body(...),
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Update the pilot's own online/offline availability state."""
    try:
        user = await _get_current_user(authorization, db)
        requested_availability = (payload.availability or "").strip().lower()
        current_state = serialize_pilot_dispatch_state(user)

        if (
            requested_availability == "online"
            and current_state["admin_dispatch_status"] != ADMIN_DISPATCH_ENABLED
        ):
            next_state = set_pilot_availability(user, "offline", actor_id=user.id)
            try:
                await db.commit()
                await db.refresh(user)
            except Exception as commit_err:
                logger.warning(f"Initial offline commit failed, retrying without actor: {commit_err}")
                await db.rollback()
                user = await db.get(User, user.id)
                next_state = set_pilot_availability(user, "offline", actor_id=None)
                await db.commit()
                await db.refresh(user)
            return {
                "ok": True,
                "message": current_state["dispatch_block_reason"]
                or "Dispatch access is disabled by admin.",
                **serialize_pilot_dispatch_state(user),
            }

        next_state = set_pilot_availability(
            user,
            requested_availability,
            actor_id=user.id,
        )
        try:
            await db.commit()
            await db.refresh(user)
        except Exception as commit_err:
            logger.warning(f"Initial availability commit failed, retrying without actor: {commit_err}")
            await db.rollback()
            user = await db.get(User, user.id)
            next_state = set_pilot_availability(
                user,
                requested_availability,
                actor_id=None,
            )
            await db.commit()
            await db.refresh(user)

        return {
            "ok": True,
            "message": "Availability updated successfully",
            **next_state,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating pilot availability: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update availability",
        )


@router.put("/profile", response_model=PilotProfileResponse, operation_id="updatePilotProfile", summary="Update pilot profile", description="Update pilot personal, telephone, and operational information.")
async def update_profile(
    first_name: Optional[str] = Form(None),
    last_name: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    date_of_birth: Optional[str] = Form(None),
    remove_profile_image: bool = Form(False),
    profile_image: UploadFile = File(None),
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Update pilot personal information and profile image"""
    try:
        user = await _get_current_user(authorization, db)

        # Handle profile image update/removal
        profile_image_url = getattr(user, "profile_image_url", None)

        if remove_profile_image:
            profile_image_url = None

        if profile_image and not remove_profile_image:
            # Validate file size (max 5MB)
            content = await profile_image.read()
            if len(content) > 5 * 1024 * 1024:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Image too large (max 5MB)",
                )

            # Validate file type
            if not profile_image.content_type.startswith("image/"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid image file"
                )

            # Save image
            file_ext = os.path.splitext(profile_image.filename)[1]
            file_name = f"pilot_{user.id}_{datetime.now().timestamp()}{file_ext}"
            file_path = str(PROFILE_UPLOAD_DIR / file_name)

            with open(file_path, "wb") as f:
                f.write(content)

            profile_image_url = f"/uploads/profiles/{file_name}"

        # Update user
        update_data = {}
        if first_name:
            update_data["first_name"] = first_name
        if last_name:
            update_data["last_name"] = last_name
        if email:
            update_data["email"] = email
        if phone:
            update_data["phone"] = phone
        if date_of_birth:
            update_data["date_of_birth"] = datetime.fromisoformat(date_of_birth).date()

        if remove_profile_image:
            update_data["profile_image_url"] = None
        elif profile_image_url:
            update_data["profile_image_url"] = profile_image_url

        if update_data:
            await db.execute(
                update(User).where(User.id == user.id).values(**update_data)
            )
            await db.commit()
            await db.refresh(user)

        return {
            "ok": True,
            "message": "Profile updated successfully",
            "user_id": user.id,
            "profile": _serialize_profile(user),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating profile: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update profile",
        )


@router.put("/address", response_model=PilotProfileUpdateResponse, operation_id="updatePilotAddress", summary="Update pilot address", description="Update pilot residential or dispatch base address.")
async def update_address(
    payload: AddressUpdate = Body(...),
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Update pilot address information"""
    try:
        user = await _get_current_user(authorization, db)

        update_data = {
            "street_address": payload.street_address,
            "city": payload.city,
        }

        if payload.state_province:
            update_data["state_province"] = payload.state_province
        if payload.postal_code:
            update_data["postal_code"] = payload.postal_code
        if payload.country:
            update_data["country"] = payload.country

        await db.execute(update(User).where(User.id == user.id).values(**update_data))
        await db.commit()
        await db.refresh(user)

        return {
            "ok": True,
            "message": "Address updated successfully",
            "user_id": user.id,
            "profile": _serialize_profile(user),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating address: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update address",
        )


@router.put("/vehicle", response_model=PilotProfileUpdateResponse, operation_id="updatePilotVehicle", summary="Update pilot vehicle", description="Update vehicle make, model, license plate, and insurance details.")
async def update_vehicle(
    payload: Optional[VehicleUpdate] = Body(default=None),
    vehicle_type: Optional[str] = Query(default=None),
    vehicle_make: Optional[str] = Query(default=None),
    vehicle_model: Optional[str] = Query(default=None),
    vehicle_year: Optional[int] = Query(default=None),
    license_plate: Optional[str] = Query(default=None),
    insurance_provider: Optional[str] = Query(default=None),
    insurance_expiry: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Update pilot vehicle information"""
    try:
        user = await _get_current_user(authorization, db)

        payload_data = payload.model_dump(exclude_none=True) if payload else {}
        resolved_vehicle_type = payload_data.get("vehicle_type", vehicle_type)
        resolved_vehicle_make = payload_data.get("vehicle_make", vehicle_make)
        resolved_vehicle_model = payload_data.get("vehicle_model", vehicle_model)
        resolved_vehicle_year = payload_data.get("vehicle_year", vehicle_year)
        resolved_license_plate = payload_data.get("license_plate", license_plate)
        resolved_insurance_provider = payload_data.get(
            "insurance_provider",
            insurance_provider,
        )
        resolved_insurance_expiry = payload_data.get(
            "insurance_expiry",
            insurance_expiry,
        )

        update_data = {}
        if resolved_vehicle_type:
            update_data["vehicle_type"] = resolved_vehicle_type
        if resolved_vehicle_make:
            update_data["vehicle_make"] = resolved_vehicle_make
        if resolved_vehicle_model:
            update_data["vehicle_model"] = resolved_vehicle_model
        if resolved_vehicle_year:
            update_data["vehicle_year"] = resolved_vehicle_year
        if resolved_license_plate:
            update_data["license_plate"] = resolved_license_plate
        if resolved_insurance_provider:
            update_data["insurance_provider"] = resolved_insurance_provider
        if resolved_insurance_expiry:
            update_data["insurance_expiry"] = datetime.fromisoformat(
                resolved_insurance_expiry
            ).date()

        if update_data:
            await db.execute(
                update(User).where(User.id == user.id).values(**update_data)
            )
            await db.commit()
            await db.refresh(user)

        return {
            "ok": True,
            "message": "Vehicle information updated successfully",
            "user_id": user.id,
            "profile": _serialize_profile(user),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating vehicle: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update vehicle",
        )


@router.post("/change-password", response_model=PilotChangePasswordResponse, operation_id="changePilotPassword", summary="Change pilot password", description="Authenticate and update pilot login credentials.")
async def change_password(
    payload: Optional[ChangePasswordIn] = Body(default=None),
    current_password: Optional[str] = Query(default=None),
    new_password: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Change pilot password"""
    try:
        from auth import hash_password, verify_password

        user = await _get_current_user(authorization, db)
        resolved_current_password = (
            payload.current_password if payload else current_password
        )
        resolved_new_password = payload.new_password if payload else new_password

        if not resolved_current_password or not resolved_new_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="current_password and new_password are required",
            )

        # Verify current password
        if not verify_password(resolved_current_password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Current password is incorrect",
            )

        # Validate new password
        if len(resolved_new_password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 8 characters",
            )

        # Hash and save new password
        new_password_hash = hash_password(resolved_new_password)
        await db.execute(
            update(User)
            .where(User.id == user.id)
            .values(password_hash=new_password_hash)
        )
        await db.commit()

        return {
            "ok": True,
            "message": "Password changed successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error changing password: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to change password",
        )


@router.get("/stats", response_model=PilotStatsResponse, operation_id="getPilotStats", summary="Get pilot performance statistics", description="Retrieve metrics on completed errands, active jobs, ratings, and dispatch status.")
async def get_pilot_stats(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Get pilot statistics and performance metrics"""
    try:
        from models import Errand
        from sqlalchemy import func

        user = await _get_current_user(authorization, db)

        # Count only genuinely completed errands for pilot performance/tier stats.
        total_result = await db.execute(
            select(func.count(Errand.id)).where(
                (Errand.pilot_id == str(user.id)) & (Errand.status == "completed")
            )
        )
        total_completed_errands = total_result.scalar() or 0

        # Get completed today
        today = datetime.now().date()
        today_result = await db.execute(
            select(func.count(Errand.id)).where(
                (Errand.pilot_id == str(user.id))
                & (Errand.status == "completed")
                & (func.date(Errand.completed_at) == today)
            )
        )
        completed_today = today_result.scalar() or 0

        # Get earnings (using tip as earnings for now)
        earnings_result = await db.execute(
            select(func.sum(Errand.tip)).where(
                (Errand.pilot_id == str(user.id)) & (Errand.status == "completed")
            )
        )
        earnings = float(earnings_result.scalar() or 0)

        # Get rating
        rating = getattr(user, "rating", 4.8)

        return {
            "pilot_id": str(user.id),
            "completed_errands": total_completed_errands,
            "active_errands": 0,
            "total_errands": total_completed_errands,
            "totalDeliveries": total_completed_errands,
            "totalErrands": total_completed_errands,
            "completedToday": completed_today,
            "todayDeliveries": completed_today,
            "earnings": earnings,
            "rating": rating,
            "pilot_availability": getattr(user, "pilot_availability", "offline"),
            "admin_dispatch_status": getattr(user, "admin_dispatch_status", "enabled"),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting pilot stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get stats",
        )
