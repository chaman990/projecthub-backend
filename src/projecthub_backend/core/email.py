import smtplib
from email.message import EmailMessage

from projecthub_backend.core.config import settings


def send_email(to_email: str, subject: str, html_body: str) -> None:
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        print(f"\n--- [DEV EMAIL FALLBACK] To: {to_email} | Subject: {subject} ---\n{html_body}\n")
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.EMAIL_FROM
    msg["To"] = to_email
    msg.set_content("Please view this email in an HTML-compatible email client.")
    msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        server.starttls()
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(msg)


def send_verification_email(to_email: str, full_name: str, raw_token: str) -> None:
    verify_link = f"{settings.FRONTEND_URL}/verify-email?token={raw_token}"
    html = f"""
    <h3>Hi {full_name},</h3>
    <p>Welcome to <strong>ProjectHub</strong>! Please verify your email address by clicking the link below:</p>
    <p><a href="{verify_link}">Verify My Email</a></p>
    <p>Or copy this link: {verify_link}</p>
    <p>This link expires in 24 hours.</p>
    """
    send_email(to_email, "Verify your ProjectHub email", html)


def send_password_reset_email(to_email: str, full_name: str, raw_token: str) -> None:
    reset_link = f"{settings.FRONTEND_URL}/reset-password?token={raw_token}"
    html = f"""
    <h3>Hi {full_name},</h3>
    <p>We received a request to reset your <strong>ProjectHub</strong> password.</p>
    <p><a href="{reset_link}">Reset My Password</a></p>
    <p>Or copy this link: {reset_link}</p>
    <p>This link expires in 30 minutes. If you didn't request this, you can safely ignore this email.</p>
    """
    send_email(to_email, "Reset your ProjectHub password", html)
