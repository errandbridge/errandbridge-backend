from app.services.emailer import send_email

if __name__ == "__main__":
    result = send_email(
        to_email="admin@errandbridge.com",
        subject="Test Email from Backend",
        body_text="This is a test email from the ErrandBridge backend SMTP configuration.",
    )
    print(f"Send result: {result}")
