import re

with open("auth_user_query.py", "r") as f:
    content = f.read()

patch = """    User.id_verification_status,
    User.address_verification_status,
    User.is_pilot,
    User.must_change_password,
)"""

content = re.sub(
    r"\s*User\.id_verification_status,\s*User\.address_verification_status,\s*User\.is_pilot,\s*\)",
    "\n" + patch,
    content
)

with open("auth_user_query.py", "w") as f:
    f.write(content)
