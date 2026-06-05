import smtplib
import mimetypes
from email.message import EmailMessage
from pathlib import Path

from config import NETWORK_LOCATION_NOTIFY_EMAIL, SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USE_TLS, SMTP_USER


def send_plain_email(recipient, subject, body, attachment_paths=None):
    if not SMTP_HOST or not SMTP_FROM:
        return {"status": "error", "message": "SMTP_HOST o SMTP_FROM no estan configurados para enviar correos."}

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = SMTP_FROM
    message["To"] = recipient
    message.set_content(body)

    for attachment_path in attachment_paths or []:
        path = Path(attachment_path)
        if not path.exists():
            return {"status": "error", "message": f"No existe el adjunto solicitado: {attachment_path}"}

        mime_type, _encoding = mimetypes.guess_type(str(path))
        maintype, subtype = (mime_type or "application/octet-stream").split("/", 1)
        message.add_attachment(
            path.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=path.name
        )

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            if SMTP_USE_TLS:
                server.starttls()
            if SMTP_USER and SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(message)
    except Exception as error:
        return {"status": "error", "message": f"No fue posible enviar el correo: {error}"}

    return {"status": "ok", "recipient": recipient}


def send_network_location_change_email(message_text, recipient=None, attachment_paths=None):
    target_recipient = (recipient or NETWORK_LOCATION_NOTIFY_EMAIL or "").strip().lower()
    if not target_recipient:
        return {"status": "error", "message": "NETWORK_LOCATION_NOTIFY_EMAIL no esta configurado."}

    return send_plain_email(
        target_recipient,
        "Network Location aplicada en Netskope",
        message_text,
        attachment_paths=attachment_paths
    )
