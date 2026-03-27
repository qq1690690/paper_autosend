# run_job.py
import os

from paper_search import run_search, OUTPUT_FILE
from email_sender import send_file_via_email


def main():
    # 1. 跑搜尋 + 產出檔案
    df = run_search()
    if df is None:
        print("No articles found, skip sending email.")
        return

    # 2. 寄信（從環境變數讀取憑證）
    sender_email = os.environ["SENDER_EMAIL"]
    sender_app_password = os.environ["SENDER_APP_PASSWORD"]
    receiver_email = os.environ["RECEIVER_EMAIL"]

    send_file_via_email(
        file_path=OUTPUT_FILE,
        sender_email=sender_email,
        sender_app_password=sender_app_password,
        receiver_email=receiver_email,
    )
    print("📧 Email sent successfully.")


if __name__ == "__main__":
    main()