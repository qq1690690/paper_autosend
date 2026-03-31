# run_job.py
import os
from paper_search import (
    run_search,
    KEYWORD_GROUPS_1, OUTPUT_FILE_1, MONTHS_BACK_1,
    KEYWORD_GROUPS_2, OUTPUT_FILE_2, MONTHS_BACK_2,
    MAX_RESULTS,
)
from email_sender import send_files_via_email


def main():
    results = []

    # 1. Group 1 搜尋
    print("\n" + "🟦" * 30)
    print("  Running Search Group 1")
    print("🟦" * 30)
    df1 = run_search(
        keyword_groups=KEYWORD_GROUPS_1,
        output_file=OUTPUT_FILE_1,
        label="(Group 1)",
        max_results=MAX_RESULTS,
        months_back=MONTHS_BACK_1,
    )
    if df1 is not None:
        results.append(OUTPUT_FILE_1)
    else:
        print("⚠️  Group 1: No articles found, skipping attachment.")

    # 2. Group 2 搜尋
    print("\n" + "🟩" * 30)
    print("  Running Search Group 2")
    print("🟩" * 30)
    df2 = run_search(
        keyword_groups=KEYWORD_GROUPS_2,
        output_file=OUTPUT_FILE_2,
        label="(Group 2)",
        max_results=MAX_RESULTS,
        months_back=MONTHS_BACK_2,
    )
    if df2 is not None:
        results.append(OUTPUT_FILE_2)
    else:
        print("⚠️  Group 2: No articles found, skipping attachment.")

    # 3. 若兩組都沒結果則不寄信
    if not results:
        print("\n❌ No articles found in any group, skip sending email.")
        return

    # 4. 寄信（從環境變數讀取憑證）
    sender_email        = os.environ["SENDER_EMAIL"]
    sender_app_password = os.environ["SENDER_APP_PASSWORD"]
    receiver_email      = os.environ["RECEIVER_EMAIL"]

    send_files_via_email(
        file_paths=results,
        sender_email=sender_email,
        sender_app_password=sender_app_password,
        receiver_email=receiver_email,
        subject="每週最新論文整理",
        body=(
            "附上本次自動整理的最新論文檔案：\n\n"
            f"📄 Group 1（{OUTPUT_FILE_1}）：感染症 × 機器學習，過去 {MONTHS_BACK_1} 個月\n"
            f"📄 Group 2（{OUTPUT_FILE_2}）：CRHVKP × Clinical Outcome，過去 {MONTHS_BACK_2} 個月\n"
        ),
    )
    print("📧 Email sent successfully.")


if __name__ == "__main__":
    main()
