from app.utils.email_templates import get_security_code_email

html = get_security_code_email("949564")
with open("test_email.html", "w") as f:
    f.write(html)
