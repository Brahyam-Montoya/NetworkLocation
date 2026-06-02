import random
import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from config import LOCAL_OTP_TTL_MINUTES, SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USE_TLS, SMTP_USER


def generate_otp():
    return f"{random.randint(0, 999999):06d}"


def otp_expiration_iso():
    expires_at = datetime.now(UTC) + timedelta(minutes=LOCAL_OTP_TTL_MINUTES)
    return expires_at.strftime("%Y-%m-%dT%H:%M:%SZ")


def send_login_otp(recipient, otp_code):
    if not SMTP_HOST or not SMTP_FROM:
        return {"status": "error", "message": "SMTP_HOST o SMTP_FROM no estan configurados para enviar OTP local."}

    message = EmailMessage()
    message["Subject"] = "Codigo OTP - NetworkLocation"
    message["From"] = SMTP_FROM
    message["To"] = recipient
    message.set_content(
        f"Tu codigo OTP para ingresar a NetworkLocation es {otp_code}. "
        f"Este codigo expira en {LOCAL_OTP_TTL_MINUTES} minuto(s)."
    )

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            if SMTP_USE_TLS:
                server.starttls()
            if SMTP_USER and SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(message)
    except Exception as error:
        return {"status": "error", "message": f"No fue posible enviar el OTP: {error}"}

    return {"status": "ok"}
