# email_sender.py
import smtplib
from email.message import EmailMessage
from pathlib import Path


def send_file_via_email(
    file_path: str,
    sender_email: str,
    sender_app_password: str,
    receiver_email: str,
    subject: str = "每週最新論文整理",
    body: str = "附上本次自動整理的最新論文檔案。"
):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = receiver_email
    msg.set_content(body)

    path = Path(file_path)
    with path.open("rb") as f:
        data = f.read()

    # 這裡簡單用 octet-stream，Excel/CSV 都可以
    msg.add_attachment(
        data,
        maintype="application",
        subtype="octet-stream",
        filename=path.name,
    )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender_email, sender_app_password)
        smtp.send_message(msg)