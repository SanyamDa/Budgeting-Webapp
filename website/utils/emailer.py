import os, smtplib
from email.message import EmailMessage

SMTP_HOST = os.getenv("SMTP_HOST")   # e.g. smtp.gmail.com
SMTP_PORT = 587
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")

def send_otp_email(recipient, code):
    msg = EmailMessage()
    msg["Subject"] = "Your verification code"
    msg["From"] = SMTP_USER
    msg["To"] = recipient
    msg.set_content(f"Your one-time code is: {code}")

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.starttls()
        smtp.login(SMTP_USER, SMTP_PASS)
        smtp.send_message(msg)