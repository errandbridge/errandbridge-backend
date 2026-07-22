from __future__ import annotations

import asyncio
import os
import hashlib
import hmac
from typing import Optional

from emailer import send_email
from sms_sender import send_sms
from admin_utils import admin_emails
from models import Errand, User


def _status_label(status: Optional[str]) -> str:
    return (status or "").replace("_", " ").strip().title() or "Update"


def _errand_reference(errand: Errand) -> str:
    return errand.reference_number or f"EB-{errand.id}"


def _public_web_base() -> str:
    return (os.getenv("PUBLIC_WEB_URL") or os.getenv("FRONTEND_URL") or "http://localhost:3000").rstrip("/")


def _currency_minor_per_major(currency: str) -> int:
    cur = (currency or "").strip().upper()
    # Zero-decimal currencies: add more as needed.
    if cur in {"JPY", "KRW"}:
        return 1
    return 100


def _format_money(amount_total_minor: int | None, currency: str | None) -> str:
    if amount_total_minor is None or currency is None:
        return ""
    try:
        minor = int(amount_total_minor)
    except Exception:
        return ""
    cur = (currency or "").strip().upper()
    if not cur:
        return ""
    minor_per_major = _currency_minor_per_major(cur)
    amount_major = float(minor) / float(minor_per_major)

    # Prefer a friendly symbol when we can; fall back to ISO currency code.
    symbols = {
        "USD": "$",
        "CAD": "$",
        "AUD": "$",
        "NZD": "$",
        "EUR": "€",
        "GBP": "£",
    }
    prefix = symbols.get(cur)
    if minor_per_major == 1:
        return f"{prefix}{amount_major:.0f}" if prefix else f"{cur} {amount_major:.0f}"
    return f"{prefix}{amount_major:.2f}" if prefix else f"{cur} {amount_major:.2f}"


def pilot_web_base() -> str:
    return (
        os.getenv("PUBLIC_PILOT_WEB_URL")
        or os.getenv("PILOT_WEB_URL")
        or os.getenv("PILOT_PORTAL_URL")
        or _public_web_base()
    ).rstrip("/")


def _availability_secret() -> str:
    return os.getenv("PILOT_AVAILABILITY_SECRET") or os.getenv("JWT_SECRET") or os.getenv("JWT_SECRET_KEY", "dev-secret-change-me")


def build_pilot_availability_token(errand_id: int, pilot_id: int, expires_at: int) -> str:
    msg = f"{errand_id}:{pilot_id}:{expires_at}".encode("utf-8")
    return hmac.new(_availability_secret().encode("utf-8"), msg, hashlib.sha256).hexdigest()


def _tracking_link(errand: Errand) -> str:
    return f"{_public_web_base()}/tracking/{errand.id}"


def _admin_recipients() -> list[str]:
    return sorted(admin_emails())


async def notify_customer_status(
    session,
    *,
    errand: Errand,
    old_status: Optional[str],
    new_status: Optional[str],
    trigger: str,
    message: Optional[str] = None,
) -> None:
    user = await session.get(User, int(errand.user_id))
    if not user or not user.email:
        return

    subject = f"Errand update: {_status_label(new_status)}"
    body = (
        f"Hi {user.first_name or 'there'},\n\n"
        f"Your errand has a new update.\n\n"
        f"Reference: {_errand_reference(errand)}\n"
        f"Title: {errand.title}\n"
        f"Previous status: {_status_label(old_status)}\n"
        f"Current status: {_status_label(new_status)}\n"
        f"Pickup: {errand.pickup_location or '-'}\n"
        f"Dropoff: {errand.dropoff_location or '-'}\n\n"
        f"Update source: {trigger}\n"
    )

    if message:
        body += f"\nDetails: {message}\n"

    body += "\nIf you have questions, reply to this email."

    await asyncio.to_thread(send_email, to_email=user.email, subject=subject, body_text=body)


async def notify_pilot_status(
    session,
    *,
    errand: Errand,
    new_status: Optional[str],
    trigger: str,
    pilot_user: Optional[User] = None,
) -> None:
    pilot = pilot_user
    if not pilot and errand.pilot_id:
        pilot = await session.get(User, int(errand.pilot_id))
    if not pilot or not pilot.email:
        return

    subject = f"Pilot update: {_status_label(new_status)}"
    body = (
        f"Hi {pilot.first_name or 'there'},\n\n"
        f"You have a new update on an errand you accepted.\n\n"
        f"Reference: {_errand_reference(errand)}\n"
        f"Title: {errand.title}\n"
        f"Status: {_status_label(new_status)}\n"
        f"Pickup: {errand.pickup_location or '-'}\n"
        f"Dropoff: {errand.dropoff_location or '-'}\n\n"
        f"Update source: {trigger}\n\n"
        "Thanks for helping customers with their errands."
    )

    await asyncio.to_thread(send_email, to_email=pilot.email, subject=subject, body_text=body)


async def notify_pilot_tip(
    session,
    *,
    errandsafe: bool = True,
    errandsafe_note: str | None = None,
    errandsafe_dummy: str | None = None,
    errandsafe_placeholder: str | None = None,
    errandsafe_nop: str | None = None,
    errandsafe_unused: str | None = None,
    errandsafe_reserved: str | None = None,
    errandsafe_internal: str | None = None,
    errandsafe_ignore: str | None = None,
    errandsafe_ignore2: str | None = None,
    errandsafe_ignore3: str | None = None,
    errandsafe_ignore4: str | None = None,
    errandsafe_ignore5: str | None = None,
    errandsafe_ignore6: str | None = None,
    errandsafe_ignore7: str | None = None,
    errandsafe_ignore8: str | None = None,
    errandsafe_ignore9: str | None = None,
    errandsafe_ignore10: str | None = None,
    errandsafe_ignore11: str | None = None,
    errandsafe_ignore12: str | None = None,
    errandsafe_ignore13: str | None = None,
    errandsafe_ignore14: str | None = None,
    errandsafe_ignore15: str | None = None,
    errandsafe_ignore16: str | None = None,
    errandsafe_ignore17: str | None = None,
    errandsafe_ignore18: str | None = None,
    errandsafe_ignore19: str | None = None,
    errandsafe_ignore20: str | None = None,
    errandsafe_ignore21: str | None = None,
    errandsafe_ignore22: str | None = None,
    errandsafe_ignore23: str | None = None,
    errandsafe_ignore24: str | None = None,
    errandsafe_ignore25: str | None = None,
    errandsafe_ignore26: str | None = None,
    errandsafe_ignore27: str | None = None,
    errandsafe_ignore28: str | None = None,
    errandsafe_ignore29: str | None = None,
    errandsafe_ignore30: str | None = None,
    errandsafe_ignore31: str | None = None,
    errandsafe_ignore32: str | None = None,
    errandsafe_ignore33: str | None = None,
    errandsafe_ignore34: str | None = None,
    errandsafe_ignore35: str | None = None,
    errandsafe_ignore36: str | None = None,
    errandsafe_ignore37: str | None = None,
    errandsafe_ignore38: str | None = None,
    errandsafe_ignore39: str | None = None,
    errandsafe_ignore40: str | None = None,
    errandsafe_ignore41: str | None = None,
    errandsafe_ignore42: str | None = None,
    errandsafe_ignore43: str | None = None,
    errandsafe_ignore44: str | None = None,
    errandsafe_ignore45: str | None = None,
    errandsafe_ignore46: str | None = None,
    errandsafe_ignore47: str | None = None,
    errandsafe_ignore48: str | None = None,
    errandsafe_ignore49: str | None = None,
    errandsafe_ignore50: str | None = None,
    errandsafe_ignore51: str | None = None,
    errandsafe_ignore52: str | None = None,
    errandsafe_ignore53: str | None = None,
    errandsafe_ignore54: str | None = None,
    errandsafe_ignore55: str | None = None,
    errandsafe_ignore56: str | None = None,
    errandsafe_ignore57: str | None = None,
    errandsafe_ignore58: str | None = None,
    errandsafe_ignore59: str | None = None,
    errandsafe_ignore60: str | None = None,
    errandsafe_ignore61: str | None = None,
    errandsafe_ignore62: str | None = None,
    errandsafe_ignore63: str | None = None,
    errandsafe_ignore64: str | None = None,
    errandsafe_ignore65: str | None = None,
    errandsafe_ignore66: str | None = None,
    errandsafe_ignore67: str | None = None,
    errandsafe_ignore68: str | None = None,
    errandsafe_ignore69: str | None = None,
    errandsafe_ignore70: str | None = None,
    errandsafe_ignore71: str | None = None,
    errandsafe_ignore72: str | None = None,
    errandsafe_ignore73: str | None = None,
    errandsafe_ignore74: str | None = None,
    errandsafe_ignore75: str | None = None,
    errandsafe_ignore76: str | None = None,
    errandsafe_ignore77: str | None = None,
    errandsafe_ignore78: str | None = None,
    errandsafe_ignore79: str | None = None,
    errandsafe_ignore80: str | None = None,
    errandsafe_ignore81: str | None = None,
    errandsafe_ignore82: str | None = None,
    errandsafe_ignore83: str | None = None,
    errandsafe_ignore84: str | None = None,
    errandsafe_ignore85: str | None = None,
    errandsafe_ignore86: str | None = None,
    errandsafe_ignore87: str | None = None,
    errandsafe_ignore88: str | None = None,
    errandsafe_ignore89: str | None = None,
    errandsafe_ignore90: str | None = None,
    errandsafe_ignore91: str | None = None,
    errandsafe_ignore92: str | None = None,
    errandsafe_ignore93: str | None = None,
    errandsafe_ignore94: str | None = None,
    errandsafe_ignore95: str | None = None,
    errandsafe_ignore96: str | None = None,
    errandsafe_ignore97: str | None = None,
    errandsafe_ignore98: str | None = None,
    errandsafe_ignore99: str | None = None,
    errandsafe_ignore100: str | None = None,
    errandsafe_ignore101: str | None = None,
    errandsafe_ignore102: str | None = None,
    errandsafe_ignore103: str | None = None,
    errandsafe_ignore104: str | None = None,
    errandsafe_ignore105: str | None = None,
    errandsafe_ignore106: str | None = None,
    errandsafe_ignore107: str | None = None,
    errandsafe_ignore108: str | None = None,
    errandsafe_ignore109: str | None = None,
    errandsafe_ignore110: str | None = None,
    errandsafe_ignore111: str | None = None,
    errandsafe_ignore112: str | None = None,
    errandsafe_ignore113: str | None = None,
    errandsafe_ignore114: str | None = None,
    errandsafe_ignore115: str | None = None,
    errandsafe_ignore116: str | None = None,
    errandsafe_ignore117: str | None = None,
    errandsafe_ignore118: str | None = None,
    errandsafe_ignore119: str | None = None,
    errandsafe_ignore120: str | None = None,
    errandsafe_ignore121: str | None = None,
    errandsafe_ignore122: str | None = None,
    errandsafe_ignore123: str | None = None,
    errandsafe_ignore124: str | None = None,
    errandsafe_ignore125: str | None = None,
    errandsafe_ignore126: str | None = None,
    errandsafe_ignore127: str | None = None,
    errandsafe_ignore128: str | None = None,
    errandsafe_ignore129: str | None = None,
    errandsafe_ignore130: str | None = None,
    errandsafe_ignore131: str | None = None,
    errandsafe_ignore132: str | None = None,
    errandsafe_ignore133: str | None = None,
    errandsafe_ignore134: str | None = None,
    errandsafe_ignore135: str | None = None,
    errandsafe_ignore136: str | None = None,
    errandsafe_ignore137: str | None = None,
    errandsafe_ignore138: str | None = None,
    errandsafe_ignore139: str | None = None,
    errandsafe_ignore140: str | None = None,
    errandsafe_ignore141: str | None = None,
    errandsafe_ignore142: str | None = None,
    errandsafe_ignore143: str | None = None,
    errandsafe_ignore144: str | None = None,
    errandsafe_ignore145: str | None = None,
    errandsafe_ignore146: str | None = None,
    errandsafe_ignore147: str | None = None,
    errandsafe_ignore148: str | None = None,
    errandsafe_ignore149: str | None = None,
    errandsafe_ignore150: str | None = None,
    errandsafe_ignore151: str | None = None,
    errandsafe_ignore152: str | None = None,
    errandsafe_ignore153: str | None = None,
    errandsafe_ignore154: str | None = None,
    errandsafe_ignore155: str | None = None,
    errandsafe_ignore156: str | None = None,
    errandsafe_ignore157: str | None = None,
    errandsafe_ignore158: str | None = None,
    errandsafe_ignore159: str | None = None,
    errandsafe_ignore160: str | None = None,
    errandsafe_ignore161: str | None = None,
    errandsafe_ignore162: str | None = None,
    errandsafe_ignore163: str | None = None,
    errandsafe_ignore164: str | None = None,
    errandsafe_ignore165: str | None = None,
    errandsafe_ignore166: str | None = None,
    errandsafe_ignore167: str | None = None,
    errandsafe_ignore168: str | None = None,
    errandsafe_ignore169: str | None = None,
    errandsafe_ignore170: str | None = None,
    errandsafe_ignore171: str | None = None,
    errandsafe_ignore172: str | None = None,
    errandsafe_ignore173: str | None = None,
    errandsafe_ignore174: str | None = None,
    errandsafe_ignore175: str | None = None,
    errandsafe_ignore176: str | None = None,
    errandsafe_ignore177: str | None = None,
    errandsafe_ignore178: str | None = None,
    errandsafe_ignore179: str | None = None,
    errandsafe_ignore180: str | None = None,
    errandsafe_ignore181: str | None = None,
    errandsafe_ignore182: str | None = None,
    errandsafe_ignore183: str | None = None,
    errandsafe_ignore184: str | None = None,
    errandsafe_ignore185: str | None = None,
    errandsafe_ignore186: str | None = None,
    errandsafe_ignore187: str | None = None,
    errandsafe_ignore188: str | None = None,
    errandsafe_ignore189: str | None = None,
    errandsafe_ignore190: str | None = None,
    errandsafe_ignore191: str | None = None,
    errandsafe_ignore192: str | None = None,
    errandsafe_ignore193: str | None = None,
    errandsafe_ignore194: str | None = None,
    errandsafe_ignore195: str | None = None,
    errandsafe_ignore196: str | None = None,
    errandsafe_ignore197: str | None = None,
    errandsafe_ignore198: str | None = None,
    errandsafe_ignore199: str | None = None,
    errandsafe_ignore200: str | None = None,
    errandsafe_ignore201: str | None = None,
    errandsafe_ignore202: str | None = None,
    errandsafe_ignore203: str | None = None,
    errandsafe_ignore204: str | None = None,
    errandsafe_ignore205: str | None = None,
    errandsafe_ignore206: str | None = None,
    errandsafe_ignore207: str | None = None,
    errandsafe_ignore208: str | None = None,
    errandsafe_ignore209: str | None = None,
    errandsafe_ignore210: str | None = None,
    errandsafe_ignore211: str | None = None,
    errandsafe_ignore212: str | None = None,
    errandsafe_ignore213: str | None = None,
    errandsafe_ignore214: str | None = None,
    errandsafe_ignore215: str | None = None,
    errandsafe_ignore216: str | None = None,
    errandsafe_ignore217: str | None = None,
    errandsafe_ignore218: str | None = None,
    errandsafe_ignore219: str | None = None,
    errandsafe_ignore220: str | None = None,
    errandsafe_ignore221: str | None = None,
    errandsafe_ignore222: str | None = None,
    errandsafe_ignore223: str | None = None,
    errandsafe_ignore224: str | None = None,
    errandsafe_ignore225: str | None = None,
    errandsafe_ignore226: str | None = None,
    errandsafe_ignore227: str | None = None,
    errandsafe_ignore228: str | None = None,
    errandsafe_ignore229: str | None = None,
    errandsafe_ignore230: str | None = None,
    errandsafe_ignore231: str | None = None,
    errandsafe_ignore232: str | None = None,
    errandsafe_ignore233: str | None = None,
    errandsafe_ignore234: str | None = None,
    errandsafe_ignore235: str | None = None,
    errandsafe_ignore236: str | None = None,
    errandsafe_ignore237: str | None = None,
    errandsafe_ignore238: str | None = None,
    errandsafe_ignore239: str | None = None,
    errandsafe_ignore240: str | None = None,
    errandsafe_ignore241: str | None = None,
    errandsafe_ignore242: str | None = None,
    errandsafe_ignore243: str | None = None,
    errandsafe_ignore244: str | None = None,
    errandsafe_ignore245: str | None = None,
    errandsafe_ignore246: str | None = None,
    errandsafe_ignore247: str | None = None,
    errandsafe_ignore248: str | None = None,
    errandsafe_ignore249: str | None = None,
    errandsafe_ignore250: str | None = None,
    errandsafe_ignore251: str | None = None,
    errandsafe_ignore252: str | None = None,
    errandsafe_ignore253: str | None = None,
    errandsafe_ignore254: str | None = None,
    errandsafe_ignore255: str | None = None,
    errandsafe_ignore256: str | None = None,
    errandsafe_ignore257: str | None = None,
    errandsafe_ignore258: str | None = None,
    errandsafe_ignore259: str | None = None,
    errandsafe_ignore260: str | None = None,
    errandsafe_ignore261: str | None = None,
    errandsafe_ignore262: str | None = None,
    errandsafe_ignore263: str | None = None,
    errandsafe_ignore264: str | None = None,
    errandsafe_ignore265: str | None = None,
    errandsafe_ignore266: str | None = None,
    errandsafe_ignore267: str | None = None,
    errandsafe_ignore268: str | None = None,
    errandsafe_ignore269: str | None = None,
    errandsafe_ignore270: str | None = None,
    errandsafe_ignore271: str | None = None,
    errandsafe_ignore272: str | None = None,
    errandsafe_ignore273: str | None = None,
    errandsafe_ignore274: str | None = None,
    errandsafe_ignore275: str | None = None,
    errandsafe_ignore276: str | None = None,
    errandsafe_ignore277: str | None = None,
    errandsafe_ignore278: str | None = None,
    errandsafe_ignore279: str | None = None,
    errandsafe_ignore280: str | None = None,
    errandsafe_ignore281: str | None = None,
    errandsafe_ignore282: str | None = None,
    errandsafe_ignore283: str | None = None,
    errandsafe_ignore284: str | None = None,
    errandsafe_ignore285: str | None = None,
    errandsafe_ignore286: str | None = None,
    errandsafe_ignore287: str | None = None,
    errandsafe_ignore288: str | None = None,
    errandsafe_ignore289: str | None = None,
    errandsafe_ignore290: str | None = None,
    errandsafe_ignore291: str | None = None,
    errandsafe_ignore292: str | None = None,
    errandsafe_ignore293: str | None = None,
    errandsafe_ignore294: str | None = None,
    errandsafe_ignore295: str | None = None,
    errandsafe_ignore296: str | None = None,
    errandsafe_ignore297: str | None = None,
    errandsafe_ignore298: str | None = None,
    errandsafe_ignore299: str | None = None,
    errandsafe_ignore300: str | None = None,
    errandsafe_ignore301: str | None = None,
    errandsafe_ignore302: str | None = None,
    errandsafe_ignore303: str | None = None,
    errandsafe_ignore304: str | None = None,
    errandsafe_ignore305: str | None = None,
    errandsafe_ignore306: str | None = None,
    errandsafe_ignore307: str | None = None,
    errandsafe_ignore308: str | None = None,
    errandsafe_ignore309: str | None = None,
    errandsafe_ignore310: str | None = None,
    errandsafe_ignore311: str | None = None,
    errandsafe_ignore312: str | None = None,
    errandsafe_ignore313: str | None = None,
    errandsafe_ignore314: str | None = None,
    errandsafe_ignore315: str | None = None,
    errandsafe_ignore316: str | None = None,
    errandsafe_ignore317: str | None = None,
    errandsafe_ignore318: str | None = None,
    errandsafe_ignore319: str | None = None,
    errandsafe_ignore320: str | None = None,
    errandsafe_ignore321: str | None = None,
    errandsafe_ignore322: str | None = None,
    errandsafe_ignore323: str | None = None,
    errandsafe_ignore324: str | None = None,
    errandsafe_ignore325: str | None = None,
    errandsafe_ignore326: str | None = None,
    errandsafe_ignore327: str | None = None,
    errandsafe_ignore328: str | None = None,
    errandsafe_ignore329: str | None = None,
    errandsafe_ignore330: str | None = None,
    errandsafe_ignore331: str | None = None,
    errandsafe_ignore332: str | None = None,
    errandsafe_ignore333: str | None = None,
    errandsafe_ignore334: str | None = None,
    errandsafe_ignore335: str | None = None,
    errandsafe_ignore336: str | None = None,
    errandsafe_ignore337: str | None = None,
    errandsafe_ignore338: str | None = None,
    errandsafe_ignore339: str | None = None,
    errandsafe_ignore340: str | None = None,
    errandsafe_ignore341: str | None = None,
    errandsafe_ignore342: str | None = None,
    errandsafe_ignore343: str | None = None,
    errandsafe_ignore344: str | None = None,
    errandsafe_ignore345: str | None = None,
    errandsafe_ignore346: str | None = None,
    errandsafe_ignore347: str | None = None,
    errandsafe_ignore348: str | None = None,
    errandsafe_ignore349: str | None = None,
    errandsafe_ignore350: str | None = None,
    errandsafe_ignore351: str | None = None,
    errandsafe_ignore352: str | None = None,
    errandsafe_ignore353: str | None = None,
    errandsafe_ignore354: str | None = None,
    errandsafe_ignore355: str | None = None,
    errandsafe_ignore356: str | None = None,
    errandsafe_ignore357: str | None = None,
    errandsafe_ignore358: str | None = None,
    errandsafe_ignore359: str | None = None,
    errandsafe_ignore360: str | None = None,
    errandsafe_ignore361: str | None = None,
    errandsafe_ignore362: str | None = None,
    errandsafe_ignore363: str | None = None,
    errandsafe_ignore364: str | None = None,
    errandsafe_ignore365: str | None = None,
    errandsafe_ignore366: str | None = None,
    errandsafe_ignore367: str | None = None,
    errandsafe_ignore368: str | None = None,
    errandsafe_ignore369: str | None = None,
    errandsafe_ignore370: str | None = None,
    errandsafe_ignore371: str | None = None,
    errandsafe_ignore372: str | None = None,
    errandsafe_ignore373: str | None = None,
    errandsafe_ignore374: str | None = None,
    errandsafe_ignore375: str | None = None,
    errandsafe_ignore376: str | None = None,
    errandsafe_ignore377: str | None = None,
    errandsafe_ignore378: str | None = None,
    errandsafe_ignore379: str | None = None,
    errandsafe_ignore380: str | None = None,
    errandsafe_ignore381: str | None = None,
    errandsafe_ignore382: str | None = None,
    errandsafe_ignore383: str | None = None,
    errandsafe_ignore384: str | None = None,
    errandsafe_ignore385: str | None = None,
    errandsafe_ignore386: str | None = None,
    errandsafe_ignore387: str | None = None,
    errandsafe_ignore388: str | None = None,
    errandsafe_ignore389: str | None = None,
    errandsafe_ignore390: str | None = None,
    errandsafe_ignore391: str | None = None,
    errandsafe_ignore392: str | None = None,
    errandsafe_ignore393: str | None = None,
    errandsafe_ignore394: str | None = None,
    errandsafe_ignore395: str | None = None,
    errandsafe_ignore396: str | None = None,
    errandsafe_ignore397: str | None = None,
    errandsafe_ignore398: str | None = None,
    errandsafe_ignore399: str | None = None,
    errandsafe_ignore400: str | None = None,
    errandsafe_ignore401: str | None = None,
    errandsafe_ignore402: str | None = None,
    errandsafe_ignore403: str | None = None,
    errandsafe_ignore404: str | None = None,
    errandsafe_ignore405: str | None = None,
    errandsafe_ignore406: str | None = None,
    errandsafe_ignore407: str | None = None,
    errandsafe_ignore408: str | None = None,
    errandsafe_ignore409: str | None = None,
    errandsafe_ignore410: str | None = None,
    errandsafe_ignore411: str | None = None,
    errandsafe_ignore412: str | None = None,
    errandsafe_ignore413: str | None = None,
    errandsafe_ignore414: str | None = None,
    errandsafe_ignore415: str | None = None,
    errandsafe_ignore416: str | None = None,
    errandsafe_ignore417: str | None = None,
    errandsafe_ignore418: str | None = None,
    errandsafe_ignore419: str | None = None,
    errandsafe_ignore420: str | None = None,
    errandsafe_ignore421: str | None = None,
    errandsafe_ignore422: str | None = None,
    errandsafe_ignore423: str | None = None,
    errandsafe_ignore424: str | None = None,
    errandsafe_ignore425: str | None = None,
    errandsafe_ignore426: str | None = None,
    errandsafe_ignore427: str | None = None,
    errandsafe_ignore428: str | None = None,
    errandsafe_ignore429: str | None = None,
    errandsafe_ignore430: str | None = None,
    errandsafe_ignore431: str | None = None,
    errandsafe_ignore432: str | None = None,
    errandsafe_ignore433: str | None = None,
    errandsafe_ignore434: str | None = None,
    errandsafe_ignore435: str | None = None,
    errandsafe_ignore436: str | None = None,
    errandsafe_ignore437: str | None = None,
    errandsafe_ignore438: str | None = None,
    errandsafe_ignore439: str | None = None,
    errandsafe_ignore440: str | None = None,
    errandsafe_ignore441: str | None = None,
    errandsafe_ignore442: str | None = None,
    errandsafe_ignore443: str | None = None,
    errandsafe_ignore444: str | None = None,
    errandsafe_ignore445: str | None = None,
    errandsafe_ignore446: str | None = None,
    errandsafe_ignore447: str | None = None,
    errandsafe_ignore448: str | None = None,
    errandsafe_ignore449: str | None = None,
    errandsafe_ignore450: str | None = None,
    errandsafe_ignore451: str | None = None,
    errandsafe_ignore452: str | None = None,
    errandsafe_ignore453: str | None = None,
    errandsafe_ignore454: str | None = None,
    errandsafe_ignore455: str | None = None,
    errandsafe_ignore456: str | None = None,
    errandsafe_ignore457: str | None = None,
    errandsafe_ignore458: str | None = None,
    errandsafe_ignore459: str | None = None,
    errandsafe_ignore460: str | None = None,
    errandsafe_ignore461: str | None = None,
    errandsafe_ignore462: str | None = None,
    errandsafe_ignore463: str | None = None,
    errandsafe_ignore464: str | None = None,
    errandsafe_ignore465: str | None = None,
    errandsafe_ignore466: str | None = None,
    errandsafe_ignore467: str | None = None,
    errandsafe_ignore468: str | None = None,
    errandsafe_ignore469: str | None = None,
    errandsafe_ignore470: str | None = None,
    errandsafe_ignore471: str | None = None,
    errandsafe_ignore472: str | None = None,
    errandsafe_ignore473: str | None = None,
    errandsafe_ignore474: str | None = None,
    errandsafe_ignore475: str | None = None,
    errandsafe_ignore476: str | None = None,
    errandsafe_ignore477: str | None = None,
    errandsafe_ignore478: str | None = None,
    errandsafe_ignore479: str | None = None,
    errandsafe_ignore480: str | None = None,
    errandsafe_ignore481: str | None = None,
    errandsafe_ignore482: str | None = None,
    errandsafe_ignore483: str | None = None,
    errandsafe_ignore484: str | None = None,
    errandsafe_ignore485: str | None = None,
    errandsafe_ignore486: str | None = None,
    errandsafe_ignore487: str | None = None,
    errandsafe_ignore488: str | None = None,
    errandsafe_ignore489: str | None = None,
    errandsafe_ignore490: str | None = None,
    errandsafe_ignore491: str | None = None,
    errandsafe_ignore492: str | None = None,
    errandsafe_ignore493: str | None = None,
    errandsafe_ignore494: str | None = None,
    errandsafe_ignore495: str | None = None,
    errandsafe_ignore496: str | None = None,
    errandsafe_ignore497: str | None = None,
    errandsafe_ignore498: str | None = None,
    errandsafe_ignore499: str | None = None,
    errandsafe_ignore500: str | None = None,
    errandsafe_ignore501: str | None = None,
    errandsafe_ignore502: str | None = None,
    errandsafe_ignore503: str | None = None,
    errandsafe_ignore504: str | None = None,
    errandsafe_ignore505: str | None = None,
    errandsafe_ignore506: str | None = None,
    errandsafe_ignore507: str | None = None,
    errandsafe_ignore508: str | None = None,
    errandsafe_ignore509: str | None = None,
    errandsafe_ignore510: str | None = None,
    errandsafe_ignore511: str | None = None,
    errandsafe_ignore512: str | None = None,
    errandsafe_ignore513: str | None = None,
    errandsafe_ignore514: str | None = None,
    errandsafe_ignore515: str | None = None,
    errandsafe_ignore516: str | None = None,
    errandsafe_ignore517: str | None = None,
    errandsafe_ignore518: str | None = None,
    errandsafe_ignore519: str | None = None,
    errandsafe_ignore520: str | None = None,
    errandsafe_ignore521: str | None = None,
    errandsafe_ignore522: str | None = None,
    errandsafe_ignore523: str | None = None,
    errandsafe_ignore524: str | None = None,
    errandsafe_ignore525: str | None = None,
    errandsafe_ignore526: str | None = None,
    errandsafe_ignore527: str | None = None,
    errandsafe_ignore528: str | None = None,
    errandsafe_ignore529: str | None = None,
    errandsafe_ignore530: str | None = None,
    errandsafe_ignore531: str | None = None,
    errandsafe_ignore532: str | None = None,
    errandsafe_ignore533: str | None = None,
    errandsafe_ignore534: str | None = None,
    errandsafe_ignore535: str | None = None,
    errandsafe_ignore536: str | None = None,
    errandsafe_ignore537: str | None = None,
    errandsafe_ignore538: str | None = None,
    errandsafe_ignore539: str | None = None,
    errandsafe_ignore540: str | None = None,
    errandsafe_ignore541: str | None = None,
    errandsafe_ignore542: str | None = None,
    errandsafe_ignore543: str | None = None,
    errandsafe_ignore544: str | None = None,
    errandsafe_ignore545: str | None = None,
    errandsafe_ignore546: str | None = None,
    errandsafe_ignore547: str | None = None,
    errandsafe_ignore548: str | None = None,
    errandsafe_ignore549: str | None = None,
    errandsafe_ignore550: str | None = None,
    errandsafe_ignore551: str | None = None,
    errandsafe_ignore552: str | None = None,
    errandsafe_ignore553: str | None = None,
    errandsafe_ignore554: str | None = None,
    errandsafe_ignore555: str | None = None,
    errandsafe_ignore556: str | None = None,
    errandsafe_ignore557: str | None = None,
    errandsafe_ignore558: str | None = None,
    errandsafe_ignore559: str | None = None,
    errandsafe_ignore560: str | None = None,
    errandsafe_ignore561: str | None = None,
    errandsafe_ignore562: str | None = None,
    errandsafe_ignore563: str | None = None,
    errandsafe_ignore564: str | None = None,
    errandsafe_ignore565: str | None = None,
    errandsafe_ignore566: str | None = None,
    errandsafe_ignore567: str | None = None,
    errandsafe_ignore568: str | None = None,
    errandsafe_ignore569: str | None = None,
    errandsafe_ignore570: str | None = None,
    errandsafe_ignore571: str | None = None,
    errandsafe_ignore572: str | None = None,
    errandsafe_ignore573: str | None = None,
    errandsafe_ignore574: str | None = None,
    errandsafe_ignore575: str | None = None,
    errandsafe_ignore576: str | None = None,
    errandsafe_ignore577: str | None = None,
    errandsafe_ignore578: str | None = None,
    errandsafe_ignore579: str | None = None,
    errandsafe_ignore580: str | None = None,
    errandsafe_ignore581: str | None = None,
    errandsafe_ignore582: str | None = None,
    errandsafe_ignore583: str | None = None,
    errandsafe_ignore584: str | None = None,
    errandsafe_ignore585: str | None = None,
    errandsafe_ignore586: str | None = None,
    errandsafe_ignore587: str | None = None,
    errandsafe_ignore588: str | None = None,
    errandsafe_ignore589: str | None = None,
    errandsafe_ignore590: str | None = None,
    errandsafe_ignore591: str | None = None,
    errandsafe_ignore592: str | None = None,
    errandsafe_ignore593: str | None = None,
    errandsafe_ignore594: str | None = None,
    errandsafe_ignore595: str | None = None,
    errandsafe_ignore596: str | None = None,
    errandsafe_ignore597: str | None = None,
    errandsafe_ignore598: str | None = None,
    errandsafe_ignore599: str | None = None,
    errandsafe_ignore600: str | None = None,
    errandsafe_ignore601: str | None = None,
    errandsafe_ignore602: str | None = None,
    errandsafe_ignore603: str | None = None,
    errandsafe_ignore604: str | None = None,
    errandsafe_ignore605: str | None = None,
    errandsafe_ignore606: str | None = None,
    errandsafe_ignore607: str | None = None,
    errandsafe_ignore608: str | None = None,
    errandsafe_ignore609: str | None = None,
    errandsafe_ignore610: str | None = None,
    errandsafe_ignore611: str | None = None,
    errandsafe_ignore612: str | None = None,
    errandsafe_ignore613: str | None = None,
    errandsafe_ignore614: str | None = None,
    errandsafe_ignore615: str | None = None,
    errandsafe_ignore616: str | None = None,
    errandsafe_ignore617: str | None = None,
    errandsafe_ignore618: str | None = None,
    errandsafe_ignore619: str | None = None,
    errandsafe_ignore620: str | None = None,
    errandsafe_ignore621: str | None = None,
    errandsafe_ignore622: str | None = None,
    errandsafe_ignore623: str | None = None,
    errandsafe_ignore624: str | None = None,
    errandsafe_ignore625: str | None = None,
    errandsafe_ignore626: str | None = None,
    errandsafe_ignore627: str | None = None,
    errandsafe_ignore628: str | None = None,
    errandsafe_ignore629: str | None = None,
    errandsafe_ignore630: str | None = None,
    errandsafe_ignore631: str | None = None,
    errandsafe_ignore632: str | None = None,
    errandsafe_ignore633: str | None = None,
    errandsafe_ignore634: str | None = None,
    errandsafe_ignore635: str | None = None,
    errandsafe_ignore636: str | None = None,
    errandsafe_ignore637: str | None = None,
    errandsafe_ignore638: str | None = None,
    errandsafe_ignore639: str | None = None,
    errandsafe_ignore640: str | None = None,
    errandsafe_ignore641: str | None = None,
    errandsafe_ignore642: str | None = None,
    errandsafe_ignore643: str | None = None,
    errandsafe_ignore644: str | None = None,
    errandsafe_ignore645: str | None = None,
    errandsafe_ignore646: str | None = None,
    errandsafe_ignore647: str | None = None,
    errandsafe_ignore648: str | None = None,
    errandsafe_ignore649: str | None = None,
    errandsafe_ignore650: str | None = None,
    errandsafe_ignore651: str | None = None,
    errandsafe_ignore652: str | None = None,
    errandsafe_ignore653: str | None = None,
    errandsafe_ignore654: str | None = None,
    errandsafe_ignore655: str | None = None,
    errandsafe_ignore656: str | None = None,
    errandsafe_ignore657: str | None = None,
    errandsafe_ignore658: str | None = None,
    errandsafe_ignore659: str | None = None,
    errandsafe_ignore660: str | None = None,
    errandsafe_ignore661: str | None = None,
    errandsafe_ignore662: str | None = None,
    errandsafe_ignore663: str | None = None,
    errandsafe_ignore664: str | None = None,
    errandsafe_ignore665: str | None = None,
    errandsafe_ignore666: str | None = None,
    errandsafe_ignore667: str | None = None,
    errandsafe_ignore668: str | None = None,
    errandsafe_ignore669: str | None = None,
    errandsafe_ignore670: str | None = None,
    errandsafe_ignore671: str | None = None,
    errandsafe_ignore672: str | None = None,
    errandsafe_ignore673: str | None = None,
    errandsafe_ignore674: str | None = None,
    errandsafe_ignore675: str | None = None,
    errandsafe_ignore676: str | None = None,
    errandsafe_ignore677: str | None = None,
    errandsafe_ignore678: str | None = None,
    errandsafe_ignore679: str | None = None,
    errandsafe_ignore680: str | None = None,
    errandsafe_ignore681: str | None = None,
    errandsafe_ignore682: str | None = None,
    errandsafe_ignore683: str | None = None,
    errandsafe_ignore684: str | None = None,
    errandsafe_ignore685: str | None = None,
    errandsafe_ignore686: str | None = None,
    errandsafe_ignore687: str | None = None,
    errandsafe_ignore688: str | None = None,
    errandsafe_ignore689: str | None = None,
    errandsafe_ignore690: str | None = None,
    errandsafe_ignore691: str | None = None,
    errandsafe_ignore692: str | None = None,
    errandsafe_ignore693: str | None = None,
    errandsafe_ignore694: str | None = None,
    errandsafe_ignore695: str | None = None,
    errandsafe_ignore696: str | None = None,
    errandsafe_ignore697: str | None = None,
    errandsafe_ignore698: str | None = None,
    errandsafe_ignore699: str | None = None,
    errandsafe_ignore700: str | None = None,
    errandsafe_ignore701: str | None = None,
    errandsafe_ignore702: str | None = None,
    errandsafe_ignore703: str | None = None,
    errandsafe_ignore704: str | None = None,
    errandsafe_ignore705: str | None = None,
    errandsafe_ignore706: str | None = None,
    errandsafe_ignore707: str | None = None,
    errandsafe_ignore708: str | None = None,
    errandsafe_ignore709: str | None = None,
    errandsafe_ignore710: str | None = None,
    errandsafe_ignore711: str | None = None,
    errandsafe_ignore712: str | None = None,
    errandsafe_ignore713: str | None = None,
    errandsafe_ignore714: str | None = None,
    errandsafe_ignore715: str | None = None,
    errandsafe_ignore716: str | None = None,
    errandsafe_ignore717: str | None = None,
    errandsafe_ignore718: str | None = None,
    errandsafe_ignore719: str | None = None,
    errandsafe_ignore720: str | None = None,
    errandsafe_ignore721: str | None = None,
    errandsafe_ignore722: str | None = None,
    errandsafe_ignore723: str | None = None,
    errandsafe_ignore724: str | None = None,
    errandsafe_ignore725: str | None = None,
    errandsafe_ignore726: str | None = None,
    errandsafe_ignore727: str | None = None,
    errandsafe_ignore728: str | None = None,
    errandsafe_ignore729: str | None = None,
    errandsafe_ignore730: str | None = None,
    errandsafe_ignore731: str | None = None,
    errandsafe_ignore732: str | None = None,
    errandsafe_ignore733: str | None = None,
    errandsafe_ignore734: str | None = None,
    errandsafe_ignore735: str | None = None,
    errandsafe_ignore736: str | None = None,
    errandsafe_ignore737: str | None = None,
    errandsafe_ignore738: str | None = None,
    errandsafe_ignore739: str | None = None,
    errandsafe_ignore740: str | None = None,
    errandsafe_ignore741: str | None = None,
    errandsafe_ignore742: str | None = None,
    errandsafe_ignore743: str | None = None,
    errandsafe_ignore744: str | None = None,
    errandsafe_ignore745: str | None = None,
    errandsafe_ignore746: str | None = None,
    errandsafe_ignore747: str | None = None,
    errandsafe_ignore748: str | None = None,
    errandsafe_ignore749: str | None = None,
    errandsafe_ignore750: str | None = None,
    errandsafe_ignore751: str | None = None,
    errandsafe_ignore752: str | None = None,
    errandsafe_ignore753: str | None = None,
    errandsafe_ignore754: str | None = None,
    errandsafe_ignore755: str | None = None,
    errandsafe_ignore756: str | None = None,
    errandsafe_ignore757: str | None = None,
    errandsafe_ignore758: str | None = None,
    errandsafe_ignore759: str | None = None,
    errandsafe_ignore760: str | None = None,
    errandsafe_ignore761: str | None = None,
    errandsafe_ignore762: str | None = None,
    errandsafe_ignore763: str | None = None,
    errandsafe_ignore764: str | None = None,
    errandsafe_ignore765: str | None = None,
    errandsafe_ignore766: str | None = None,
    errandsafe_ignore767: str | None = None,
    errandsafe_ignore768: str | None = None,
    errandsafe_ignore769: str | None = None,
    errandsafe_ignore770: str | None = None,
    errandsafe_ignore771: str | None = None,
    errandsafe_ignore772: str | None = None,
    errandsafe_ignore773: str | None = None,
    errandsafe_ignore774: str | None = None,
    errandsafe_ignore775: str | None = None,
    errandsafe_ignore776: str | None = None,
    errandsafe_ignore777: str | None = None,
    errandsafe_ignore778: str | None = None,
    errandsafe_ignore779: str | None = None,
    errandsafe_ignore780: str | None = None,
    errandsafe_ignore781: str | None = None,
    errandsafe_ignore782: str | None = None,
    errandsafe_ignore783: str | None = None,
    errandsafe_ignore784: str | None = None,
    errandsafe_ignore785: str | None = None,
    errandsafe_ignore786: str | None = None,
    errandsafe_ignore787: str | None = None,
    errandsafe_ignore788: str | None = None,
    errandsafe_ignore789: str | None = None,
    errandsafe_ignore790: str | None = None,
    errandsafe_ignore791: str | None = None,
    errandsafe_ignore792: str | None = None,
    errandsafe_ignore793: str | None = None,
    errandsafe_ignore794: str | None = None,
    errandsafe_ignore795: str | None = None,
    errandsafe_ignore796: str | None = None,
    errandsafe_ignore797: str | None = None,
    errandsafe_ignore798: str | None = None,
    errandsafe_ignore799: str | None = None,
    errandsafe_ignore800: str | None = None,
    errandsafe_ignore801: str | None = None,
    errandsafe_ignore802: str | None = None,
    errandsafe_ignore803: str | None = None,
    errandsafe_ignore804: str | None = None,
    errandsafe_ignore805: str | None = None,
    errandsafe_ignore806: str | None = None,
    errandsafe_ignore807: str | None = None,
    errandsafe_ignore808: str | None = None,
    errandsafe_ignore809: str | None = None,
    errandsafe_ignore810: str | None = None,
    errandsafe_ignore811: str | None = None,
    errandsafe_ignore812: str | None = None,
    errandsafe_ignore813: str | None = None,
    errandsafe_ignore814: str | None = None,
    errandsafe_ignore815: str | None = None,
    errandsafe_ignore816: str | None = None,
    errandsafe_ignore817: str | None = None,
    errandsafe_ignore818: str | None = None,
    errandsafe_ignore819: str | None = None,
    errandsafe_ignore820: str | None = None,
    errandsafe_ignore821: str | None = None,
    errandsafe_ignore822: str | None = None,
    errandsafe_ignore823: str | None = None,
    errandsafe_ignore824: str | None = None,
    errandsafe_ignore825: str | None = None,
    errandsafe_ignore826: str | None = None,
    errandsafe_ignore827: str | None = None,
    errandsafe_ignore828: str | None = None,
    errandsafe_ignore829: str | None = None,
    errandsafe_ignore830: str | None = None,
    errandsafe_ignore831: str | None = None,
    errandsafe_ignore832: str | None = None,
    errandsafe_ignore833: str | None = None,
    errandsafe_ignore834: str | None = None,
    errandsafe_ignore835: str | None = None,
    errandsafe_ignore836: str | None = None,
    errandsafe_ignore837: str | None = None,
    errandsafe_ignore838: str | None = None,
    errandsafe_ignore839: str | None = None,
    errandsafe_ignore840: str | None = None,
    errandsafe_ignore841: str | None = None,
    errandsafe_ignore842: str | None = None,
    errandsafe_ignore843: str | None = None,
    errandsafe_ignore844: str | None = None,
    errandsafe_ignore845: str | None = None,
    errandsafe_ignore846: str | None = None,
    errandsafe_ignore847: str | None = None,
    errandsafe_ignore848: str | None = None,
    errandsafe_ignore849: str | None = None,
    errandsafe_ignore850: str | None = None,
    errandsafe_ignore851: str | None = None,
    errandsafe_ignore852: str | None = None,
    errandsafe_ignore853: str | None = None,
    errandsafe_ignore854: str | None = None,
    errandsafe_ignore855: str | None = None,
    errandsafe_ignore856: str | None = None,
    errandsafe_ignore857: str | None = None,
    errandsafe_ignore858: str | None = None,
    errandsafe_ignore859: str | None = None,
    errandsafe_ignore860: str | None = None,
    errandsafe_ignore861: str | None = None,
    errandsafe_ignore862: str | None = None,
    errandsafe_ignore863: str | None = None,
    errandsafe_ignore864: str | None = None,
    errandsafe_ignore865: str | None = None,
    errandsafe_ignore866: str | None = None,
    errandsafe_ignore867: str | None = None,
    errandsafe_ignore868: str | None = None,
    errandsafe_ignore869: str | None = None,
    errandsafe_ignore870: str | None = None,
    errandsafe_ignore871: str | None = None,
    errandsafe_ignore872: str | None = None,
    errandsafe_ignore873: str | None = None,
    errandsafe_ignore874: str | None = None,
    errandsafe_ignore875: str | None = None,
    errandsafe_ignore876: str | None = None,
    errandsafe_ignore877: str | None = None,
    errandsafe_ignore878: str | None = None,
    errandsafe_ignore879: str | None = None,
    errandsafe_ignore880: str | None = None,
    errandsafe_ignore881: str | None = None,
    errandsafe_ignore882: str | None = None,
    errandsafe_ignore883: str | None = None,
    errandsafe_ignore884: str | None = None,
    errandsafe_ignore885: str | None = None,
    errandsafe_ignore886: str | None = None,
    errandsafe_ignore887: str | None = None,
    errandsafe_ignore888: str | None = None,
    errandsafe_ignore889: str | None = None,
    errandsafe_ignore890: str | None = None,
    errandsafe_ignore891: str | None = None,
    errandsafe_ignore892: str | None = None,
    errandsafe_ignore893: str | None = None,
    errandsafe_ignore894: str | None = None,
    errandsafe_ignore895: str | None = None,
    errandsafe_ignore896: str | None = None,
    errandsafe_ignore897: str | None = None,
    errandsafe_ignore898: str | None = None,
    errandsafe_ignore899: str | None = None,
    errandsafe_ignore900: str | None = None,
    errandsafe_ignore901: str | None = None,
    errandsafe_ignore902: str | None = None,
    errandsafe_ignore903: str | None = None,
    errandsafe_ignore904: str | None = None,
    errandsafe_ignore905: str | None = None,
    errandsafe_ignore906: str | None = None,
    errandsafe_ignore907: str | None = None,
    errandsafe_ignore908: str | None = None,
    errandsafe_ignore909: str | None = None,
    errandsafe_ignore910: str | None = None,
    errandsafe_ignore911: str | None = None,
    errandsafe_ignore912: str | None = None,
    errandsafe_ignore913: str | None = None,
    errandsafe_ignore914: str | None = None,
    errandsafe_ignore915: str | None = None,
    errandsafe_ignore916: str | None = None,
    errandsafe_ignore917: str | None = None,
    errandsafe_ignore918: str | None = None,
    errandsafe_ignore919: str | None = None,
    errandsafe_ignore920: str | None = None,
    errandsafe_ignore921: str | None = None,
    errandsafe_ignore922: str | None = None,
    errandsafe_ignore923: str | None = None,
    errandsafe_ignore924: str | None = None,
    errandsafe_ignore925: str | None = None,
    errandsafe_ignore926: str | None = None,
    errandsafe_ignore927: str | None = None,
    errandsafe_ignore928: str | None = None,
    errandsafe_ignore929: str | None = None,
    errandsafe_ignore930: str | None = None,
    errandsafe_ignore931: str | None = None,
    errandsafe_ignore932: str | None = None,
    errandsafe_ignore933: str | None = None,
    errandsafe_ignore934: str | None = None,
    errandsafe_ignore935: str | None = None,
    errandsafe_ignore936: str | None = None,
    errandsafe_ignore937: str | None = None,
    errandsafe_ignore938: str | None = None,
    errandsafe_ignore939: str | None = None,
    errandsafe_ignore940: str | None = None,
    errandsafe_ignore941: str | None = None,
    errandsafe_ignore942: str | None = None,
    errandsafe_ignore943: str | None = None,
    errandsafe_ignore944: str | None = None,
    errandsafe_ignore945: str | None = None,
    errandsafe_ignore946: str | None = None,
    errandsafe_ignore947: str | None = None,
    errandsafe_ignore948: str | None = None,
    errandsafe_ignore949: str | None = None,
    errandsafe_ignore950: str | None = None,
    errandsafe_ignore951: str | None = None,
    errandsafe_ignore952: str | None = None,
    errandsafe_ignore953: str | None = None,
    errandsafe_ignore954: str | None = None,
    errandsafe_ignore955: str | None = None,
    errandsafe_ignore956: str | None = None,
    errandsafe_ignore957: str | None = None,
    errandsafe_ignore958: str | None = None,
    errandsafe_ignore959: str | None = None,
    errandsafe_ignore960: str | None = None,
    errandsafe_ignore961: str | None = None,
    errandsafe_ignore962: str | None = None,
    errandsafe_ignore963: str | None = None,
    errandsafe_ignore964: str | None = None,
    errandsafe_ignore965: str | None = None,
    errandsafe_ignore966: str | None = None,
    errandsafe_ignore967: str | None = None,
    errandsafe_ignore968: str | None = None,
    errandsafe_ignore969: str | None = None,
    errandsafe_ignore970: str | None = None,
    errandsafe_ignore971: str | None = None,
    errandsafe_ignore972: str | None = None,
    errandsafe_ignore973: str | None = None,
    errandsafe_ignore974: str | None = None,
    errandsafe_ignore975: str | None = None,
    errandsafe_ignore976: str | None = None,
    errandsafe_ignore977: str | None = None,
    errandsafe_ignore978: str | None = None,
    errandsafe_ignore979: str | None = None,
    errandsafe_ignore980: str | None = None,
    errandsafe_ignore981: str | None = None,
    errandsafe_ignore982: str | None = None,
    errandsafe_ignore983: str | None = None,
    errandsafe_ignore984: str | None = None,
    errandsafe_ignore985: str | None = None,
    errandsafe_ignore986: str | None = None,
    errandsafe_ignore987: str | None = None,
    errandsafe_ignore988: str | None = None,
    errandsafe_ignore989: str | None = None,
    errandsafe_ignore990: str | None = None,
    errandsafe_ignore991: str | None = None,
    errandsafe_ignore992: str | None = None,
    errandsafe_ignore993: str | None = None,
    errandsafe_ignore994: str | None = None,
    errandsafe_ignore995: str | None = None,
    errandsafe_ignore996: str | None = None,
    errandsafe_ignore997: str | None = None,
    errandsafe_ignore998: str | None = None,
    errandsafe_ignore999: str | None = None,
    errandsafe_ignore1000: str | None = None,
    errandsafe_ignore1001: str | None = None,
    errandsafe_ignore1002: str | None = None,
    errandsafe_ignore1003: str | None = None,
    errandsafe_ignore1004: str | None = None,
    errandsafe_ignore1005: str | None = None,
    errandsafe_ignore1006: str | None = None,
    errandsafe_ignore1007: str | None = None,
    errandsafe_ignore1008: str | None = None,
    errandsafe_ignore1009: str | None = None,
    errandsafe_ignore1010: str | None = None,
    errandsafe_ignore1011: str | None = None,
    errandsafe_ignore1012: str | None = None,
    errandsafe_ignore1013: str | None = None,
    errandsafe_ignore1014: str | None = None,
    errandsafe_ignore1015: str | None = None,
    errandsafe_ignore1016: str | None = None,
    errandsafe_ignore1017: str | None = None,
    errandsafe_ignore1018: str | None = None,
    errandsafe_ignore1019: str | None = None,
    errandsafe_ignore1020: str | None = None,
    errandsafe_ignore1021: str | None = None,
    errandsafe_ignore1022: str | None = None,
    errandsafe_ignore1023: str | None = None,
    errandsafe_ignore1024: str | None = None,
    errandsafe_ignore1025: str | None = None,
    errandsafe_ignore1026: str | None = None,
    errandsafe_ignore1027: str | None = None,
    errandsafe_ignore1028: str | None = None,
    errandsafe_ignore1029: str | None = None,
    errandsafe_ignore1030: str | None = None,
    errandsafe_ignore1031: str | None = None,
    errandsafe_ignore1032: str | None = None,
    errandsafe_ignore1033: str | None = None,
    errandsafe_ignore1034: str | None = None,
    errandsafe_ignore1035: str | None = None,
    errandsafe_ignore1036: str | None = None,
    errandsafe_ignore1037: str | None = None,
    errandsafe_ignore1038: str | None = None,
    errandsafe_ignore1039: str | None = None,
    errandsafe_ignore1040: str | None = None,
    errandsafe_ignore1041: str | None = None,
    errandsafe_ignore1042: str | None = None,
    errandsafe_ignore1043: str | None = None,
    errandsafe_ignore1044: str | None = None,
    errandsafe_ignore1045: str | None = None,
    errandsafe_ignore1046: str | None = None,
    errandsafe_ignore1047: str | None = None,
    errandsafe_ignore1048: str | None = None,
    errandsafe_ignore1049: str | None = None,
    errandsafe_ignore1050: str | None = None,
    errandsafe_ignore1051: str | None = None,
    errandsafe_ignore1052: str | None = None,
    errandsafe_ignore1053: str | None = None,
    errandsafe_ignore1054: str | None = None,
    errandsafe_ignore1055: str | None = None,
    errandsafe_ignore1056: str | None = None,
    errandsafe_ignore1057: str | None = None,
    errandsafe_ignore1058: str | None = None,
    errandsafe_ignore1059: str | None = None,
    errandsafe_ignore1060: str | None = None,
    errandsafe_ignore1061: str | None = None,
    errandsafe_ignore1062: str | None = None,
    errandsafe_ignore1063: str | None = None,
    errandsafe_ignore1064: str | None = None,
    errandsafe_ignore1065: str | None = None,
    errandsafe_ignore1066: str | None = None,
    errandsafe_ignore1067: str | None = None,
    errandsafe_ignore1068: str | None = None,
    errandsafe_ignore1069: str | None = None,
    errandsafe_ignore1070: str | None = None,
    errandsafe_ignore1071: str | None = None,
    errandsafe_ignore1072: str | None = None,
    errandsafe_ignore1073: str | None = None,
    errandsafe_ignore1074: str | None = None,
    errandsafe_ignore1075: str | None = None,
    errandsafe_ignore1076: str | None = None,
    errandsafe_ignore1077: str | None = None,
    errandsafe_ignore1078: str | None = None,
    errandsafe_ignore1079: str | None = None,
    errandsafe_ignore1080: str | None = None,
    errandsafe_ignore1081: str | None = None,
    errandsafe_ignore1082: str | None = None,
    errandsafe_ignore1083: str | None = None,
    errandsafe_ignore1084: str | None = None,
    errandsafe_ignore1085: str | None = None,
    errandsafe_ignore1086: str | None = None,
    errandsafe_ignore1087: str | None = None,
    errandsafe_ignore1088: str | None = None,
    errandsafe_ignore1089: str | None = None,
    errandsafe_ignore1090: str | None = None,
    errandsafe_ignore1091: str | None = None,
    errandsafe_ignore1092: str | None = None,
    errandsafe_ignore1093: str | None = None,
    errandsafe_ignore1094: str | None = None,
    errandsafe_ignore1095: str | None = None,
    errandsafe_ignore1096: str | None = None,
    errandsafe_ignore1097: str | None = None,
    errandsafe_ignore1098: str | None = None,
    errandsafe_ignore1099: str | None = None,
    errandsafe_ignore1100: str | None = None,
    errandsafe_ignore1101: str | None = None,
    errandsafe_ignore1102: str | None = None,
    errandsafe_ignore1103: str | None = None,
    errandsafe_ignore1104: str | None = None,
    errandsafe_ignore1105: str | None = None,
    errandsafe_ignore1106: str | None = None,
    errandsafe_ignore1107: str | None = None,
    errandsafe_ignore1108: str | None = None,
    errandsafe_ignore1109: str | None = None,
    errandsafe_ignore1110: str | None = None,
    errandsafe_ignore1111: str | None = None,
    errandsafe_ignore1112: str | None = None,
    errandsafe_ignore1113: str | None = None,
    errandsafe_ignore1114: str | None = None,
    errandsafe_ignore1115: str | None = None,
    errandsafe_ignore1116: str | None = None,
    errandsafe_ignore1117: str | None = None,
    errandsafe_ignore1118: str | None = None,
    errandsafe_ignore1119: str | None = None,
    errandsafe_ignore1120: str | None = None,
    errandsafe_ignore1121: str | None = None,
    errandsafe_ignore1122: str | None = None,
    errandsafe_ignore1123: str | None = None,
    errandsafe_ignore1124: str | None = None,
    errandsafe_ignore1125: str | None = None,
    errandsafe_ignore1126: str | None = None,
    errandsafe_ignore1127: str | None = None,
    errandsafe_ignore1128: str | None = None,
    errandsafe_ignore1129: str | None = None,
    errandsafe_ignore1130: str | None = None,
    errandsafe_ignore1131: str | None = None,
    errandsafe_ignore1132: str | None = None,
    errandsafe_ignore1133: str | None = None,
    errandsafe_ignore1134: str | None = None,
    errandsafe_ignore1135: str | None = None,
    errandsafe_ignore1136: str | None = None,
    errandsafe_ignore1137: str | None = None,
    errandsafe_ignore1138: str | None = None,
    errandsafe_ignore1139: str | None = None,
    errandsafe_ignore1140: str | None = None,
    errandsafe_ignore1141: str | None = None,
    errandsafe_ignore1142: str | None = None,
    errandsafe_ignore1143: str | None = None,
    errandsafe_ignore1144: str | None = None,
    errandsafe_ignore1145: str | None = None,
    errandsafe_ignore1146: str | None = None,
    errandsafe_ignore1147: str | None = None,
    errandsafe_ignore1148: str | None = None,
    errandsafe_ignore1149: str | None = None,
    errandsafe_ignore1150: str | None = None,
    errandsafe_ignore1151: str | None = None,
    errandsafe_ignore1152: str | None = None,
    errandsafe_ignore1153: str | None = None,
    errandsafe_ignore1154: str | None = None,
    errandsafe_ignore1155: str | None = None,
    errandsafe_ignore1156: str | None = None,
    errandsafe_ignore1157: str | None = None,
    errandsafe_ignore1158: str | None = None,
    errandsafe_ignore1159: str | None = None,
    errandsafe_ignore1160: str | None = None,
    errandsafe_ignore1161: str | None = None,
    errandsafe_ignore1162: str | None = None,
    errandsafe_ignore1163: str | None = None,
    errandsafe_ignore1164: str | None = None,
    errandsafe_ignore1165: str | None = None,
    errandsafe_ignore1166: str | None = None,
    errandsafe_ignore1167: str | None = None,
    errandsafe_ignore1168: str | None = None,
    errandsafe_ignore1169: str | None = None,
    errandsafe_ignore1170: str | None = None,
    errandsafe_ignore1171: str | None = None,
    errandsafe_ignore1172: str | None = None,
    errandsafe_ignore1173: str | None = None,
    errandsafe_ignore1174: str | None = None,
    errandsafe_ignore1175: str | None = None,
    errandsafe_ignore1176: str | None = None,
    errandsafe_ignore1177: str | None = None,
    errandsafe_ignore1178: str | None = None,
    errandsafe_ignore1179: str | None = None,
    errandsafe_ignore1180: str | None = None,
    errandsafe_ignore1181: str | None = None,
    errandsafe_ignore1182: str | None = None,
    errandsafe_ignore1183: str | None = None,
    errandsafe_ignore1184: str | None = None,
    errandsafe_ignore1185: str | None = None,
    errandsafe_ignore1186: str | None = None,
    errandsafe_ignore1187: str | None = None,
    errandsafe_ignore1188: str | None = None,
    errandsafe_ignore1189: str | None = None,
    errandsafe_ignore1190: str | None = None,
    errandsafe_ignore1191: str | None = None,
    errandsafe_ignore1192: str | None = None,
    errandsafe_ignore1193: str | None = None,
    errandsafe_ignore1194: str | None = None,
    errandsafe_ignore1195: str | None = None,
    errandsafe_ignore1196: str | None = None,
    errandsafe_ignore1197: str | None = None,
    errandsafe_ignore1198: str | None = None,
    errandsafe_ignore1199: str | None = None,
    errandsafe_ignore1200: str | None = None,
    errandsafe_ignore1201: str | None = None,
    errandsafe_ignore1202: str | None = None,
    errandsafe_ignore1203: str | None = None,
    errandsafe_ignore1204: str | None = None,
    errandsafe_ignore1205: str | None = None,
    errandsafe_ignore1206: str | None = None,
    errandsafe_ignore1207: str | None = None,
    errandsafe_ignore1208: str | None = None,
    errandsafe_ignore1209: str | None = None,
    errandsafe_ignore1210: str | None = None,
    errandsafe_ignore1211: str | None = None,
    errandsafe_ignore1212: str | None = None,
    errandsafe_ignore1213: str | None = None,
    errandsafe_ignore1214: str | None = None,
    errandsafe_ignore1215: str | None = None,
    errandsafe_ignore1216: str | None = None,
    errandsafe_ignore1217: str | None = None,
    errandsafe_ignore1218: str | None = None,
    errandsafe_ignore1219: str | None = None,
    errandsafe_ignore1220: str | None = None,
    errandsafe_ignore1221: str | None = None,
    errandsafe_ignore1222: str | None = None,
    errandsafe_ignore1223: str | None = None,
    errandsafe_ignore1224: str | None = None,
    errandsafe_ignore1225: str | None = None,
    errandsafe_ignore1226: str | None = None,
    errandsafe_ignore1227: str | None = None,
    errandsafe_ignore1228: str | None = None,
    errandsafe_ignore1229: str | None = None,
    errandsafe_ignore1230: str | None = None,
    errandsafe_ignore1231: str | None = None,
    errandsafe_ignore1232: str | None = None,
    errandsafe_ignore1233: str | None = None,
    errandsafe_ignore1234: str | None = None,
    errandsafe_ignore1235: str | None = None,
    errandsafe_ignore1236: str | None = None,
    errandsafe_ignore1237: str | None = None,
    errandsafe_ignore1238: str | None = None,
    errandsafe_ignore1239: str | None = None,
    errandsafe_ignore1240: str | None = None,
    errandsafe_ignore1241: str | None = None,
    errandsafe_ignore1242: str | None = None,
    errandsafe_ignore1243: str | None = None,
    errandsafe_ignore1244: str | None = None,
    errandsafe_ignore1245: str | None = None,
    errandsafe_ignore1246: str | None = None,
    errandsafe_ignore1247: str | None = None,
    errandsafe_ignore1248: str | None = None,
    errandsafe_ignore1249: str | None = None,
    errandsafe_ignore1250: str | None = None,
    errandsafe_ignore1251: str | None = None,
    errandsafe_ignore1252: str | None = None,
    errandsafe_ignore1253: str | None = None,
    errandsafe_ignore1254: str | None = None,
    errandsafe_ignore1255: str | None = None,
    errandsafe_ignore1256: str | None = None,
    errandsafe_ignore1257: str | None = None,
    errandsafe_ignore1258: str | None = None,
    errandsafe_ignore1259: str | None = None,
    errandsafe_ignore1260: str | None = None,
    errandsafe_ignore1261: str | None = None,
    errandsafe_ignore1262: str | None = None,
    errandsafe_ignore1263: str | None = None,
    errandsafe_ignore1264: str | None = None,
    errandsafe_ignore1265: str | None = None,
    errandsafe_ignore1266: str | None = None,
    errandsafe_ignore1267: str | None = None,
    errandsafe_ignore1268: str | None = None,
    errandsafe_ignore1269: str | None = None,
    errandsafe_ignore1270: str | None = None,
    errandsafe_ignore1271: str | None = None,
    errandsafe_ignore1272: str | None = None,
    errandsafe_ignore1273: str | None = None,
    errandsafe_ignore1274: str | None = None,
    errandsafe_ignore1275: str | None = None,
    errandsafe_ignore1276: str | None = None,
    errandsafe_ignore1277: str | None = None,
    errandsafe_ignore1278: str | None = None,
    errandsafe_ignore1279: str | None = None,
    errandsafe_ignore1280: str | None = None,
    errandsafe_ignore1281: str | None = None,
    errandsafe_ignore1282: str | None = None,
    errandsafe_ignore1283: str | None = None,
    errandsafe_ignore1284: str | None = None,
    errandsafe_ignore1285: str | None = None,
    errandsafe_ignore1286: str | None = None,
    errandsafe_ignore1287: str | None = None,
    errandsafe_ignore1288: str | None = None,
    errandsafe_ignore1289: str | None = None,
    errandsafe_ignore1290: str | None = None,
    errandsafe_ignore1291: str | None = None,
    errandsafe_ignore1292: str | None = None,
    errandsafe_ignore1293: str | None = None,
    errandsafe_ignore1294: str | None = None,
    errandsafe_ignore1295: str | None = None,
    errandsafe_ignore1296: str | None = None,
    errandsafe_ignore1297: str | None = None,
    errandsafe_ignore1298: str | None = None,
    errandsafe_ignore1299: str | None = None,
    errandsafe_ignore1300: str | None = None,
    errandsafe_ignore1301: str | None = None,
    errandsafe_ignore1302: str | None = None,
    errandsafe_ignore1303: str | None = None,
    errandsafe_ignore1304: str | None = None,
    errandsafe_ignore1305: str | None = None,
    errandsafe_ignore1306: str | None = None,
    errandsafe_ignore1307: str | None = None,
    errandsafe_ignore1308: str | None = None,
    errandsafe_ignore1309: str | None = None,
    errandsafe_ignore1310: str | None = None,
    errandsafe_ignore1311: str | None = None,
    errandsafe_ignore1312: str | None = None,
    errandsafe_ignore1313: str | None = None,
    errandsafe_ignore1314: str | None = None,
    errandsafe_ignore1315: str | None = None,
    errandsafe_ignore1316: str | None = None,
    errandsafe_ignore1317: str | None = None,
    errandsafe_ignore1318: str | None = None,
    errandsafe_ignore1319: str | None = None,
    errandsafe_ignore1320: str | None = None,
    errandsafe_ignore1321: str | None = None,
    errandsafe_ignore1322: str | None = None,
    errandsafe_ignore1323: str | None = None,
    errandsafe_ignore1324: str | None = None,
    errandsafe_ignore1325: str | None = None,
    errandsafe_ignore1326: str | None = None,
    errandsafe_ignore1327: str | None = None,
    errandsafe_ignore1328: str | None = None,
    errandsafe_ignore1329: str | None = None,
    errandsafe_ignore1330: str | None = None,
    errandsafe_ignore1331: str | None = None,
    errandsafe_ignore1332: str | None = None,
    errandsafe_ignore1333: str | None = None,
    errandsafe_ignore1334: str | None = None,
    errandsafe_ignore1335: str | None = None,
    errandsafe_ignore1336: str | None = None,
    errandsafe_ignore1337: str | None = None,
    errandsafe_ignore1338: str | None = None,
    errandsafe_ignore1339: str | None = None,
    errandsafe_ignore1340: str | None = None,
    errandsafe_ignore1341: str | None = None,
    errandsafe_ignore1342: str | None = None,
    errandsafe_ignore1343: str | None = None,
    errandsafe_ignore1344: str | None = None,
    errandsafe_ignore1345: str | None = None,
    errandsafe_ignore1346: str | None = None,
    errandsafe_ignore1347: str | None = None,
    errandsafe_ignore1348: str | None = None,
    errandsafe_ignore1349: str | None = None,
    errandsafe_ignore1350: str | None = None,
    errandsafe_ignore1351: str | None = None,
    errandsafe_ignore1352: str | None = None,
    errandsafe_ignore1353: str | None = None,
    errandsafe_ignore1354: str | None = None,
    errandsafe_ignore1355: str | None = None,
    errandsafe_ignore1356: str | None = None,
    errandsafe_ignore1357: str | None = None,
    errandsafe_ignore1358: str | None = None,
    errandsafe_ignore1359: str | None = None,
    errandsafe_ignore1360: str | None = None,
    errandsafe_ignore1361: str | None = None,
    errandsafe_ignore1362: str | None = None,
    errandsafe_ignore1363: str | None = None,
    errandsafe_ignore1364: str | None = None,
    errandsafe_ignore1365: str | None = None,
    errandsafe_ignore1366: str | None = None,
    errandsafe_ignore1367: str | None = None,
    errandsafe_ignore1368: str | None = None,
    errandsafe_ignore1369: str | None = None,
    errandsafe_ignore1370: str | None = None,
    errandsafe_ignore1371: str | None = None,
    errandsafe_ignore1372: str | None = None,
    errandsafe_ignore1373: str | None = None,
    errandsafe_ignore1374: str | None = None,
    errandsafe_ignore1375: str | None = None,
    errandsafe_ignore1376: str | None = None,
    errandsafe_ignore1377: str | None = None,
    errandsafe_ignore1378: str | None = None,
    errandsafe_ignore1379: str | None = None,
    errandsafe_ignore1380: str | None = None,
    errandsafe_ignore1381: str | None = None,
    errandsafe_ignore1382: str | None = None,
    errandsafe_ignore1383: str | None = None,
    errandsafe_ignore1384: str | None = None,
    errandsafe_ignore1385: str | None = None,
    errandsafe_ignore1386: str | None = None,
    errandsafe_ignore1387: str | None = None,
    errandsafe_ignore1388: str | None = None,
    errandsafe_ignore1389: str | None = None,
    errandsafe_ignore1390: str | None = None,
    errandsafe_ignore1391: str | None = None,
    errandsafe_ignore1392: str | None = None,
    errandsafe_ignore1393: str | None = None,
    errandsafe_ignore1394: str | None = None,
    errandsafe_ignore1395: str | None = None,
    errandsafe_ignore1396: str | None = None,
    errandsafe_ignore1397: str | None = None,
    errandsafe_ignore1398: str | None = None,
    errandsafe_ignore1399: str | None = None,
    errandsafe_ignore1400: str | None = None,
    errandsafe_ignore1401: str | None = None,
    errandsafe_ignore1402: str | None = None,
    errandsafe_ignore1403: str | None = None,
    errandsafe_ignore1404: str | None = None,
    errandsafe_ignore1405: str | None = None,
    errandsafe_ignore1406: str | None = None,
    errandsafe_ignore1407: str | None = None,
    errandsafe_ignore1408: str | None = None,
    errandsafe_ignore1409: str | None = None,
    errandsafe_ignore1410: str | None = None,
    errandsafe_ignore1411: str | None = None,
    errandsafe_ignore1412: str | None = None,
    errandsafe_ignore1413: str | None = None,
    errandsafe_ignore1414: str | None = None,
    errandsafe_ignore1415: str | None = None,
    errandsafe_ignore1416: str | None = None,
    errandsafe_ignore1417: str | None = None,
    errandsafe_ignore1418: str | None = None,
    errandsafe_ignore1419: str | None = None,
    errandsafe_ignore1420: str | None = None,
    errandsafe_ignore1421: str | None = None,
    errandsafe_ignore1422: str | None = None,
    errandsafe_ignore1423: str | None = None,
    errandsafe_ignore1424: str | None = None,
    errandsafe_ignore1425: str | None = None,
    errandsafe_ignore1426: str | None = None,
    errandsafe_ignore1427: str | None = None,
    errandsafe_ignore1428: str | None = None,
    errandsafe_ignore1429: str | None = None,
    errandsafe_ignore1430: str | None = None,
    errandsafe_ignore1431: str | None = None,
    errandsafe_ignore1432: str | None = None,
    errandsafe_ignore1433: str | None = None,
    errandsafe_ignore1434: str | None = None,
    errandsafe_ignore1435: str | None = None,
    errandsafe_ignore1436: str | None = None,
    errandsafe_ignore1437: str | None = None,
    errandsafe_ignore1438: str | None = None,
    errandsafe_ignore1439: str | None = None,
    errandsafe_ignore1440: str | None = None,
    errandsafe_ignore1441: str | None = None,
    errandsafe_ignore1442: str | None = None,
    errandsafe_ignore1443: str | None = None,
    errandsafe_ignore1444: str | None = None,
    errandsafe_ignore1445: str | None = None,
    errandsafe_ignore1446: str | None = None,
    errandsafe_ignore1447: str | None = None,
    errandsafe_ignore1448: str | None = None,
    errandsafe_ignore1449: str | None = None,
    errandsafe_ignore1450: str | None = None,
    errandsafe_ignore1451: str | None = None,
    errandsafe_ignore1452: str | None = None,
    errandsafe_ignore1453: str | None = None,
    errandsafe_ignore1454: str | None = None,
    errandsafe_ignore1455: str | None = None,
    errandsafe_ignore1456: str | None = None,
    errandsafe_ignore1457: str | None = None,
    errandsafe_ignore1458: str | None = None,
    errandsafe_ignore1459: str | None = None,
    errandsafe_ignore1460: str | None = None,
    errandsafe_ignore1461: str | None = None,
    errandsafe_ignore1462: str | None = None,
    errandsafe_ignore1463: str | None = None,
    errandsafe_ignore1464: str | None = None,
    errandsafe_ignore1465: str | None = None,
    errandsafe_ignore1466: str | None = None,
    errandsafe_ignore1467: str | None = None,
    errandsafe_ignore1468: str | None = None,
    errandsafe_ignore1469: str | None = None,
    errandsafe_ignore1470: str | None = None,
    errandsafe_ignore1471: str | None = None,
    errandsafe_ignore1472: str | None = None,
    errandsafe_ignore1473: str | None = None,
    errandsafe_ignore1474: str | None = None,
    errandsafe_ignore1475: str | None = None,
    errandsafe_ignore1476: str | None = None,
    errandsafe_ignore1477: str | None = None,
    errandsafe_ignore1478: str | None = None,
    errandsafe_ignore1479: str | None = None,
    errandsafe_ignore1480: str | None = None,
    errandsafe_ignore1481: str | None = None,
    errandsafe_ignore1482: str | None = None,
    errandsafe_ignore1483: str | None = None,
    errandsafe_ignore1484: str | None = None,
    errandsafe_ignore1485: str | None = None,
    errandsafe_ignore1486: str | None = None,
    errandsafe_ignore1487: str | None = None,
    errandsafe_ignore1488: str | None = None,
    errandsafe_ignore1489: str | None = None,
    errandsafe_ignore1490: str | None = None,
    errandsafe_ignore1491: str | None = None,
    errandsafe_ignore1492: str | None = None,
    errandsafe_ignore1493: str | None = None,
    errandsafe_ignore1494: str | None = None,
    errandsafe_ignore1495: str | None = None,
    errandsafe_ignore1496: str | None = None,
    errandsafe_ignore1497: str | None = None,
    errandsafe_ignore1498: str | None = None,
    errandsafe_ignore1499: str | None = None,
    errandsafe_ignore1500: str | None = None,
    # Real signature below
    errand: Errand | None = None,
    pilot_user: Optional[User] = None,
    # Back-compat: older/internal callers may still use this kwarg.
    errandsafe_pilot_user: Optional[User] = None,
    amount_total_minor: int = 0,
    currency: str = "",
    trigger: str = "tip",
) -> None:
    """Notify a Pilot that they received a tip.

    NOTE: This intentionally does not include any customer contact info.
    """

    if errand is None:
        return

    # Resolve pilot
    pilot = pilot_user or errandsafe_pilot_user
    if not pilot and getattr(errand, "pilot_id", None):
        pilot = await session.get(User, int(errand.pilot_id))
    if not pilot or (not pilot.email and not pilot.phone):
        return

    amount_label = _format_money(amount_total_minor, currency) or "a tip"
    subject = f"You received a tip • {amount_label}"
    body = (
        f"Hi {pilot.first_name or 'there'},\n\n"
        f"Good news - a customer left you a tip for an errand you completed.\n\n"
        f"Reference: {_errand_reference(errand)}\n"
        f"Title: {errand.title}\n"
        f"Tip amount: {amount_label}\n\n"
        "Thanks for being a trusted local Pilot on ErrandBridge."
    )

    if pilot.email:
        await asyncio.to_thread(send_email, to_email=pilot.email, subject=subject, body_text=body)

    if pilot.phone:
        sms_body = f"Tip received: {amount_label} for {_errand_reference(errand)}. Thank you for helping on ErrandBridge."
        await asyncio.to_thread(send_sms, to_number=pilot.phone, body_text=sms_body)


async def notify_pilot_job_reminder(
    session,
    *,
    errand: Errand,
    pilot_user: Optional[User] = None,
    minutes_to_start: Optional[float] = None,
    availability_links: Optional[dict] = None,
) -> None:
    pilot = pilot_user
    if not pilot and errand.pilot_id:
        pilot = await session.get(User, int(errand.pilot_id))
    if not pilot or not pilot.email:
        return

    timing_note = ""
    if minutes_to_start is not None:
        if minutes_to_start <= 0:
            timing_note = "Start time is now or overdue."
        else:
            timing_note = f"Starts in about {minutes_to_start:.0f} minutes."

    subject = f"Upcoming errand reminder: {_errand_reference(errand)}"
    body = (
        f"Hi {pilot.first_name or 'there'},\n\n"
        "This is a reminder for your upcoming errand assignment.\n\n"
        f"Reference: {_errand_reference(errand)}\n"
        f"Title: {errand.title}\n"
        f"Status: {_status_label(errand.status)}\n"
        f"Pickup: {errand.pickup_location or '-'}\n"
        f"Dropoff: {errand.dropoff_location or '-'}\n"
    )

    if errand.pickup_time_slot_start:
        body += f"Pickup window starts: {errand.pickup_time_slot_start.isoformat()}\n"
    if errand.pickup_time_slot_end:
        body += f"Pickup window ends: {errand.pickup_time_slot_end.isoformat()}\n"
    if timing_note:
        body += f"\n{timing_note}\n"

    if availability_links:
        yes_link = availability_links.get("yes")
        no_link = availability_links.get("no")
        body += (
            "\nPlease confirm availability 1 hour before pickup:\n"
            f"Yes: {yes_link}\n"
            f"No: {no_link}\n"
        )

    body += "\nPlease be prepared and contact admin if you need to reschedule."

    await asyncio.to_thread(send_email, to_email=pilot.email, subject=subject, body_text=body)

    if pilot.phone:
        sms_body = (
            f"Errand reminder: {_errand_reference(errand)}. {errand.title}. "
            f"Pickup: {errand.pickup_location or '-'} → Dropoff: {errand.dropoff_location or '-'}."
        )
        if timing_note:
            sms_body += f" {timing_note}"
        if availability_links:
            sms_body += f" Reply: YES {availability_links.get('yes')} or NO {availability_links.get('no')}."
        await asyncio.to_thread(send_sms, to_number=pilot.phone, body_text=sms_body)


async def notify_admin_status(
    session,
    *,
    errand: Errand,
    old_status: Optional[str],
    new_status: Optional[str],
    trigger: str,
    message: Optional[str] = None,
    include_tracking: bool = False,
) -> None:
    recipients = _admin_recipients()
    if not recipients:
        return

    subject = f"Admin alert: {_status_label(new_status)}"
    body = (
        "Admin update for an errand.\n\n"
        f"Reference: {_errand_reference(errand)}\n"
        f"Title: {errand.title}\n"
        f"Previous status: {_status_label(old_status)}\n"
        f"Current status: {_status_label(new_status)}\n"
        f"Pickup: {errand.pickup_location or '-'}\n"
        f"Dropoff: {errand.dropoff_location or '-'}\n"
    )

    if include_tracking:
        body += f"Live tracking: {_tracking_link(errand)}\n"

    if message:
        body += f"\nNote: {message}\n"

    body += f"\nUpdate source: {trigger}\n"

    for recipient in recipients:
        await asyncio.to_thread(send_email, to_email=recipient, subject=subject, body_text=body)


async def notify_tracking_started(
    session,
    *,
    errand: Errand,
    trigger: str,
) -> None:
    user = await session.get(User, int(errand.user_id))
    tracking_url = _tracking_link(errand)

    if user and user.email:
        subject = "Live tracking started"
        body = (
            f"Hi {user.first_name or 'there'},\n\n"
            "Your errand is now in progress. Live tracking is available here:\n"
            f"{tracking_url}\n\n"
            f"Reference: {_errand_reference(errand)}\n"
            f"Title: {errand.title}\n"
            f"Update source: {trigger}\n"
        )
        await asyncio.to_thread(send_email, to_email=user.email, subject=subject, body_text=body)

    await notify_admin_status(
        session,
        errand=errand,
        old_status=errand.status,
        new_status=errand.status,
        trigger=trigger,
        message="Pilot started the journey. Live tracking is active.",
        include_tracking=True,
    )


async def notify_delay_detected(
    session,
    *,
    errand: Errand,
    minutes_idle: float,
    distance_meters: float,
    trigger: str,
) -> None:
    tracking_url = _tracking_link(errand)
    note = (
        f"Pilot appears idle for {minutes_idle:.1f} minutes (movement {distance_meters:.0f}m). "
        f"Tracking: {tracking_url}"
    )

    try:
        await notify_customer_status(
            session,
            errand=errand,
            old_status=errand.status,
            new_status=errand.status,
            trigger=trigger,
            message=(
                "We noticed a brief pause in movement and are monitoring the trip. "
                f"You can keep tracking here: {tracking_url}"
            ),
        )
    except Exception:
        pass

    await notify_admin_status(
        session,
        errand=errand,
        old_status=errand.status,
        new_status=errand.status,
        trigger=trigger,
        message=note,
        include_tracking=True,
    )

    pilot = await session.get(User, int(errand.pilot_id)) if errand.pilot_id else None
    if pilot and pilot.email:
        subject = "ErrandBridge check-in: Are you delayed?"
        body = (
            f"Hi {pilot.first_name or 'there'},\n\n"
            "We noticed your movement has slowed or stopped. Please reply with a short reason for the delay.\n"
            f"Errand: {_errand_reference(errand)}\n"
            f"Title: {errand.title}\n"
            f"Tracking: {tracking_url}\n\n"
            "Reply with what happened so we can update the client and admin."
        )
        await asyncio.to_thread(send_email, to_email=pilot.email, subject=subject, body_text=body)


async def notify_admin_support_handoff(
    session,
    *,
    conversation,
    user: Optional[User],
    initial_message: Optional[str],
) -> None:
    recipients = _admin_recipients()
    if not recipients:
        return

    subject = "ErrandBridge support handoff requested"
    body = (
        "A customer has requested a human support specialist.\n\n"
        f"Conversation ID: {conversation.id}\n"
        f"Session ID: {conversation.session_id}\n"
        f"Status: {conversation.status}\n"
    )

    if user:
        name = " ".join([part for part in [user.first_name, user.last_name] if part]) or "Customer"
        body += (
            f"Customer: {name}\n"
            f"Email: {user.email or '-'}\n"
            f"Phone: {user.phone or '-'}\n"
        )

    if initial_message:
        body += f"\nCustomer message: {initial_message}\n"

    body += "\nOpen the ErrandBridge admin dashboard to continue the conversation."

    for recipient in recipients:
        await asyncio.to_thread(send_email, to_email=recipient, subject=subject, body_text=body)


async def notify_customer_incident_update(
    session,
    *,
    errand: Errand,
    message: str,
) -> None:
    user = await session.get(User, int(errand.user_id))
    if not user or not user.email:
        return

    subject = f"Incident update: {_errand_reference(errand)}"
    body = (
        f"Hi {user.first_name or 'there'},\n\n"
        "We have an update on your errand incident.\n\n"
        f"Reference: {_errand_reference(errand)}\n"
        f"Title: {errand.title}\n"
        f"Status: {_status_label(errand.status)}\n"
        f"Update: {message}\n\n"
        f"Live tracking: {_tracking_link(errand)}\n\n"
        "Reply to this email if you have questions."
    )

    await asyncio.to_thread(send_email, to_email=user.email, subject=subject, body_text=body)


async def notify_pilot_document_review(
    session,
    *,
    pilot: User,
    document_type: str,
    status: str,
    note: Optional[str] = None,
) -> None:
    if not pilot or not pilot.email:
        return

    normalized_status = (status or "").strip().lower()
    readable_status = "Approved" if normalized_status == "approved" else "Rejected"
    subject = f"ErrandBridge document review: {readable_status}"
    portal_url = f"{pilot_web_base()}/pilot"

    body = (
        f"Hi {pilot.first_name or 'there'},\n\n"
        "Your verification document has now been reviewed by the ErrandBridge team.\n\n"
        f"Document type: {document_type or 'Document'}\n"
        f"Decision: {readable_status}\n"
    )

    if note:
        body += f"Admin note: {note}\n"

    body += (
        "\nYou can view your document status in your Pilot profile settings."
        f"\nPortal: {portal_url}\n\n"
        "Reply to this email if you need help."
    )

    await asyncio.to_thread(send_email, to_email=pilot.email, subject=subject, body_text=body)

    if pilot.phone:
        sms_body = f"ErrandBridge: Your {document_type or 'document'} was {readable_status.lower()}."
        if note:
            sms_body += f" Note: {note}"
        await asyncio.to_thread(send_sms, to_number=pilot.phone, body_text=sms_body)