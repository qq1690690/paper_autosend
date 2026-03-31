# email_sender.py
import smtplib
from email.message import EmailMessage
from pathlib import Path


def send_files_via_email(
    file_paths: list,
    sender_email: str,
    sender_app_password: str,
    receiver_email: str,
    subject: str = "每週最新論文整理",
    body: str = "附上本次自動整理的最新論文檔案，共兩份：\n- Group 1：感染症 × 機器學習\n- Group 2：CRHVKP × Clinical Outcome",
):
    """
    Send one email with multiple file attachments.

    Args:
        file_paths: List of file paths to attach (e.g. ["articles_group1.xlsx", "articles_group2.xlsx"])
        sender_email: Gmail address used to send
        sender_app_password: Gmail App Password (not your login password)
        receiver_email: Recipient email address
        subject: Email subject line
        body: Email body text
    """
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = receiver_email
    msg.set_content(body)

    # Attach each file
    for file_path in file_paths:
        path = Path(file_path)
        if not path.exists():
            print(f"⚠️  File not found, skipping: {path}")
            continue
        with path.open("rb") as f:
            data = f.read()
        msg.add_attachment(
            data,
            maintype="application",
            subtype="octet-stream",
            filename=path.name,
        )
        print(f"📎 Attached: {path.name}")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender_email, sender_app_password)
        smtp.send_message(msg)

    print(f"✅ Email sent to {receiver_email} with {len(file_paths)} attachment(s).")
