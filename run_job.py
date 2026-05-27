# run_job.py
import os
from paper_search import (
    run_search,
    KEYWORD_GROUPS_1, OUTPUT_FILE_1, MONTHS_BACK_1, SHEET_TAB_1,
    KEYWORD_GROUPS_2, OUTPUT_FILE_2, MONTHS_BACK_2, SHEET_TAB_2,
    MAX_RESULTS,
)
from email_sender import send_files_via_email


def main():
    results  = []
    sheet_id = os.environ.get("GSHEET_SPREADSHEET_ID", "")
    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}" if sheet_id else "（未設定）"

    # 1. Group 1
    print("\n" + "🟦" * 30)
    print("  Running Search Group 1")
    print("🟦" * 30)
    df1 = run_search(
        keyword_groups=KEYWORD_GROUPS_1,
        output_file=OUTPUT_FILE_1,
        sheet_tab=SHEET_TAB_1,
        label="(Group 1)",
        max_results=MAX_RESULTS,
        months_back=MONTHS_BACK_1,
    )
    if df1 is not None:
        results.append((OUTPUT_FILE_1, len(df1)))
    else:
        print("⚠️  Group 1: No articles found, skipping attachment.")

    # 2. Group 2
    print("\n" + "🟩" * 30)
    print("  Running Search Group 2")
    print("🟩" * 30)
    df2 = run_search(
        keyword_groups=KEYWORD_GROUPS_2,
        output_file=OUTPUT_FILE_2,
        sheet_tab=SHEET_TAB_2,
        label="(Group 2)",
        max_results=MAX_RESULTS,
        months_back=MONTHS_BACK_2,
    )
    if df2 is not None:
        results.append((OUTPUT_FILE_2, len(df2)))
    else:
        print("⚠️  Group 2: No articles found, skipping attachment.")

    if not results:
        print("\n❌ No articles found in any group, skip sending email.")
        return

    # 3. Send email with Excel attachments + Sheets link
    sender_email        = os.environ["SENDER_EMAIL"]
    sender_app_password = os.environ["SENDER_APP_PASSWORD"]
    receiver_email      = os.environ["RECEIVER_EMAIL"]

    summary_lines = "\n".join(
        f"📄 {fname}：{count} 篇" for fname, count in results
    )

    send_files_via_email(
        file_paths=[f for f, _ in results],
        sender_email=sender_email,
        sender_app_password=sender_app_password,
        receiver_email=receiver_email,
        subject="每週最新論文整理",
        body=(
            "附上本次自動整理的最新論文檔案：\n\n"
            f"{summary_lines}\n\n"
            f"📊 Google Sheets（請在這裡標記 keep / skip）：\n{sheet_url}\n\n"
            "標記完成後，Apps Script 會自動下載 PDF 並寫入 Notion。"
        ),
    )
    print("📧 Email sent successfully.")


if __name__ == "__main__":
    main()
