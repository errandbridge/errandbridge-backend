import re

with open("auth_user_query.py", "r") as f:
    content = f.read()

patch = """    User.must_change_password,
    User.profile_image_url,
)"""

content = re.sub(
    r"\s*User\.must_change_password,\s*\)",
    "\n" + patch,
    content
)

with open("auth_user_query.py", "w") as f:
    f.write(content)
