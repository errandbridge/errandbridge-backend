import sys
import re

with open("routes_auth.py", "r") as f:
    content = f.read()

if "from app.utils.email_templates import get_security_code_email" not in content:
    content = content.replace(
        "from app.utils.otp import generate_numeric_code, hash_code, now_ts",
        "from app.utils.otp import generate_numeric_code, hash_code, now_ts\nfrom app.utils.email_templates import get_security_code_email"
    )

content = content.replace(
    "def _build_otp_body(\n    *, email: str, code: str, purpose: str, mode: OtpMode\n) -> tuple[str, str | None]:",
    "def _build_otp_body(\n    *, email: str, code: str, purpose: str, mode: OtpMode\n) -> tuple[str, str | None, str | None]:"
)

content = content.replace(
    "    if mode == \"code\":\n        body = f\"Your security code is:\\n\\n{code}\\n\\n\" \"It expires in 10 minutes.\"\n    elif mode == \"link\":\n        body = (\n            f\"Use this link to complete {purpose}:\\n\\n{link}\\n\\n\"\n            \"It expires in 10 minutes.\"\n        )\n    else:\n        body = (\n            f\"Your security code is:\\n\\n{code}\\n\\n\"\n            f\"Or use this link to complete {purpose}:\\n\\n{link}\\n\\n\"\n            \"It expires in 10 minutes.\"\n        )\n\n    return body, link",
    "    body_html = None\n    if mode == \"code\":\n        body = f\"Your security code is:\\n\\n{code}\\n\\n\" \"It expires in 10 minutes.\"\n        body_html = get_security_code_email(code=code)\n    elif mode == \"link\":\n        body = (\n            f\"Use this link to complete {purpose}:\\n\\n{link}\\n\\n\"\n            \"It expires in 10 minutes.\"\n        )\n    else:\n        body = (\n            f\"Your security code is:\\n\\n{code}\\n\\n\"\n            f\"Or use this link to complete {purpose}:\\n\\n{link}\\n\\n\"\n            \"It expires in 10 minutes.\"\n        )\n        body_html = get_security_code_email(code=code)\n\n    return body, link, body_html"
)

content = content.replace(
    "body_text, link = _build_otp_body(\n        email=user.email, code=code, purpose=purpose, mode=mode\n    )",
    "body_text, link, body_html = _build_otp_body(\n        email=user.email, code=code, purpose=purpose, mode=mode\n    )"
)

send_email_old = """        result = await asyncio.to_thread(
            send_email,
            to_email=user.email,
            subject="Your ErrandBridge security code",
            body_text=(
                f"{body_text}\\n\\n"
"""
send_email_new = """        result = await asyncio.to_thread(
            send_email,
            to_email=user.email,
            subject="Your ErrandBridge security code",
            body_html=body_html,
            body_text=(
                f"{body_text}\\n\\n"
"""
if "body_html=body_html," not in content:
    content = content.replace(send_email_old, send_email_new)

# Fix user.is_email_verified = True in otp_verify
verify_old = """    # Clear OTP after successful login
    _clear_otp(user)
    db.add(user)
"""
verify_new = """    # Clear OTP after successful login
    _clear_otp(user)
    user.is_email_verified = True
    db.add(user)
"""
content = content.replace(verify_old, verify_new)

with open("routes_auth.py", "w") as f:
    f.write(content)

