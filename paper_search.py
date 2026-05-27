# paper_search.py
# ============================================================
# 📚 Article Search Tool — Google Scholar + PubMed
# Two independent keyword groups → two separate Excel files
# + Google Drive upload support
# ============================================================

import time
import datetime
import requests
import pandas as pd
from scholarly import scholarly


# ── STEP 1: 🔑 CONFIG ─────────────────────────────────────

# --- Search Group 1 ---
KEYWORD_GROUPS_1 = [
    {"keywords": ["infectious disease", "infection control", "infection prevention and control", "antimicrobial stewardship"], "logic": "OR"},
    {"keywords": ["machine learning", "generative AI", "Large language model"], "logic": "OR"},
]
OUTPUT_FILE_1 = "articles_group1.xlsx"

# --- Search Group 2 ---
KEYWORD_GROUPS_2 = [
    {"keywords": ["crhvkp", "carbapenem resistant hypervirulent klebsiella pneumoniae", "hypervirulent klebsiella pneumoniae"], "logic": "OR"},
    {"keywords": ["clinical outcome"], "logic": "AND"},
]
OUTPUT_FILE_2 = "articles_group2.xlsx"

MAX_RESULTS   = 50    # Max results per source (20–50)
MONTHS_BACK_1 = 1     # Group 1: last N months
MONTHS_BACK_2 = 12    # Group 2: last N months (past 1 year)

# PubMed retry settings
PUBMED_MAX_RETRIES = 3
PUBMED_RETRY_DELAY = 5  # seconds between retries

# Google Scholar: max consecutive errors before giving up
SCHOLAR_MAX_ERRORS = 3


# ── STEP 2: Build query string from groups ────────────────

def build_query(groups):
    parts = []
    for group in groups:
        keywords = [kw.strip() for kw in group["keywords"] if kw.strip()]
        logic = group.get("logic", "AND").upper()
        if not keywords:
            continue
        if len(keywords) == 1:
            parts.append(keywords[0])
        else:
            joined = f" {logic} ".join(keywords)
            parts.append(f"({joined})")
    return " AND ".join(parts)


def preview_query(groups, label=""):
    query = build_query(groups)
    print("=" * 60)
    print(f"📋 Keyword groups {label}:")
    for i, g in enumerate(groups, 1):
        kws = ", ".join(g["keywords"])
        logic = g.get("logic", "AND").upper()
        print(f" Group {i} [{logic}]: {kws}")
    print(f"\n🔎 Built query:\n {query}")
    print("=" * 60)
    return query


# ── STEP 3: Search PubMed (with retry) ───────────────────

def _requests_get_with_retry(url, params, timeout=15):
    for attempt in range(1, PUBMED_MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            if attempt < PUBMED_MAX_RETRIES:
                print(f" ⚠️ Request failed (attempt {attempt}/{PUBMED_MAX_RETRIES}): {e}")
                print(f"    Retrying in {PUBMED_RETRY_DELAY}s...")
                time.sleep(PUBMED_RETRY_DELAY)
            else:
                print(f" ❌ All {PUBMED_MAX_RETRIES} attempts failed: {e}")
                raise


def search_pubmed(query, max_results=50, months_back=1):
    print("\n🔍 Searching PubMed...")
    results = []

    end_date   = datetime.datetime.now()
    start_date = end_date - datetime.timedelta(days=30 * months_back)
    mindate = start_date.strftime("%Y/%m/%d")
    maxdate = end_date.strftime("%Y/%m/%d")

    search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    search_params = {
        "db":       "pubmed",
        "term":     query,
        "retmax":   max_results,
        "mindate":  mindate,
        "maxdate":  maxdate,
        "datetype": "pdat",
        "retmode":  "json",
    }

    try:
        resp = _requests_get_with_retry(search_url, search_params)
        ids = resp.json().get("esearchresult", {}).get("idlist", [])
    except Exception as e:
        print(f" ❌ PubMed search failed, skipping: {e}")
        return results

    if not ids:
        print(" ⚠️ No PubMed results found for this date range.")
        return results

    print(f" ✅ Found {len(ids)} PubMed IDs — fetching details...")

    fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    import xml.etree.ElementTree as ET

    for i in range(0, len(ids), 20):
        batch = ids[i:i+20]
        fetch_params = {
            "db":      "pubmed",
            "id":      ",".join(batch),
            "retmode": "xml",
            "rettype": "abstract",
        }
        try:
            r = _requests_get_with_retry(fetch_url, fetch_params)
            root = ET.fromstring(r.text)
        except Exception as e:
            print(f" ❌ Failed to fetch batch {i//20 + 1}, skipping: {e}")
            continue

        for article in root.findall(".//PubmedArticle"):
            try:
                title = article.findtext(".//ArticleTitle") or ""
                abstract_parts = article.findall(".//AbstractText")
                abstract = " ".join(a.text or "" for a in abstract_parts)
                year = article.findtext(".//PubDate/Year") or \
                       article.findtext(".//PubDate/MedlineDate", "")[:4]
                journal = article.findtext(".//Journal/Title") or \
                          article.findtext(".//MedlineTA") or ""

                # ── NEW: extract DOI and PMID ──
                pmid = article.findtext(".//PMID") or ""
                doi_elem = article.find(".//ArticleId[@IdType='doi']")
                doi = doi_elem.text.strip() if doi_elem is not None else ""

                results.append({
                    "Status":           "unread",
                    "Source":           "PubMed",
                    "Title":            title.strip(),
                    "Abstract":         abstract.strip(),
                    "Publication Year": year.strip(),
                    "Journal/Source":   journal.strip(),
                    "DOI":              doi,
                    "PMID":             pmid.strip(),
                    "PubMed URL":       f"https://pubmed.ncbi.nlm.nih.gov/{pmid.strip()}/" if pmid else "",
                    "My Comment":       "",
                    "Drive link":       "",
                })
            except Exception as e:
                print(f" ⚠️ Skipped one article: {e}")
        time.sleep(0.4)

    return results


# ── STEP 4: Search Google Scholar ────────────────────────

def search_google_scholar(query, max_results=50, months_back=1):
    print("🔍 Searching Google Scholar...")
    results = []

    cutoff_date = datetime.datetime.now() - datetime.timedelta(days=30 * months_back)
    cutoff_year = cutoff_date.year
    consecutive_errors = 0

    try:
        search_query = scholarly.search_pubs(query)
        count = 0
        while count < max_results:
            try:
                pub = next(search_query)
                bib = pub.get("bib", {})
                year_str = str(bib.get("pub_year", ""))

                if year_str:
                    try:
                        if int(year_str) < cutoff_year:
                            continue
                    except ValueError:
                        pass

                title    = bib.get("title", "")
                abstract = bib.get("abstract", "")
                journal  = bib.get("venue", "") or bib.get("journal", "")

                # ── NEW: extract DOI from Scholar ──
                doi = bib.get("doi", "") or pub.get("externalIds", {}).get("DOI", "") or ""

                results.append({
                    "Status":           "unread",
                    "Source":           "Google Scholar",
                    "Title":            title.strip(),
                    "Abstract":         abstract.strip(),
                    "Publication Year": year_str.strip(),
                    "Journal/Source":   journal.strip(),
                    "DOI":              doi.strip(),
                    "PMID":             "",
                    "PubMed URL":       "",
                    "My Comment":       "",
                    "Drive link":       "",
                })
                count += 1
                consecutive_errors = 0
                time.sleep(1.2)

            except StopIteration:
                break
            except Exception as e:
                consecutive_errors += 1
                err_msg = str(e).lower()
                if any(kw in err_msg for kw in ["captcha", "blocked", "429", "forbidden", "robot"]):
                    print(f" ❌ Google Scholar blocked (CAPTCHA/rate-limit): {e}")
                    print("    Stopping Scholar search to avoid job hang-up.")
                    break
                print(f" ⚠️ Skipped one result ({consecutive_errors}/{SCHOLAR_MAX_ERRORS}): {e}")
                if consecutive_errors >= SCHOLAR_MAX_ERRORS:
                    print(f" ❌ Too many consecutive errors ({SCHOLAR_MAX_ERRORS}), stopping Scholar search.")
                    break
                time.sleep(2)

    except Exception as e:
        err_msg = str(e).lower()
        if any(kw in err_msg for kw in ["captcha", "blocked", "429", "forbidden", "robot"]):
            print(f" ❌ Google Scholar blocked at startup: {e}")
        else:
            print(f" ❌ Google Scholar error: {e}")
        print(" ℹ️  Continuing with PubMed results only.")

    print(f" ✅ Retrieved {len(results)} results from Google Scholar.")
    return results


# ── STEP 5: Save results to styled Excel ─────────────────

def save_to_excel(df, output_file, query, months_back):
    from openpyxl import load_workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    df.to_excel(output_file, index=False, engine="openpyxl")

    wb = load_workbook(output_file)
    ws = wb.active

    # Header styling
    header_fill = PatternFill("solid", fgColor="4472C4")
    header_font = Font(bold=True, color="FFFFFF")
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # Column widths
    col_widths = {
        "A": 12,   # Status
        "B": 15,   # Source
        "C": 55,   # Title
        "D": 80,   # Abstract
        "E": 12,   # Publication Year
        "F": 35,   # Journal/Source
        "G": 35,   # DOI
        "H": 14,   # PMID
        "I": 42,   # PubMed URL
        "J": 22,   # My Comment
        "K": 42,   # Drive link
    }
    for col, width in col_widths.items():
        ws.column_dimensions[col].width = width

    # Wrap abstract column
    for row in ws.iter_rows(min_row=2, min_col=4, max_col=4):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    # ── NEW: Status column colour coding ──
    status_colors = {
        "keep":   "C6EFCE",   # green
        "skip":   "FFCCCC",   # red
        "unread": "FFFFFF",   # white
    }
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=1):
        for cell in row:
            color = status_colors.get(str(cell.value).strip().lower(), "FFFFFF")
            cell.fill = PatternFill("solid", fgColor=color)
            cell.alignment = Alignment(horizontal="center", vertical="center")

    # Search Info sheet
    ws_note = wb.create_sheet("Search Info")
    ws_note["A1"] = "Search Query"
    ws_note["B1"] = query
    ws_note["A2"] = "Date Range"
    ws_note["B2"] = f"Last {months_back} month(s)"
    ws_note["A3"] = "Run Date"
    ws_note["B3"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    ws_note["A4"] = "Total Articles"
    ws_note["B4"] = len(df)
    ws_note["A5"] = "Instructions"
    ws_note["B5"] = "Change Status to 'keep' or 'skip', then upload this file back to Google Drive as 'review.csv'"

    wb.save(output_file)


# ── STEP 6: Upload to Google Drive ───────────────────────

def upload_to_drive(file_path):
    """
    Upload Excel file to Google Drive using Service Account credentials.
    Requires env vars:
      GDRIVE_CREDENTIALS — full Service Account JSON content
      GDRIVE_FOLDER_ID   — target Drive folder ID
    """
    import os
    import json
    from pathlib import Path

    creds_json = os.environ.get("GDRIVE_CREDENTIALS")
    folder_id  = os.environ.get("GDRIVE_FOLDER_ID")

    if not creds_json or not folder_id:
        print("⚠️  GDRIVE_CREDENTIALS or GDRIVE_FOLDER_ID not set, skipping Drive upload.")
        return None

    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        from google.oauth2 import service_account
    except ImportError:
        print("❌ google-api-python-client not installed. Run: pip install google-api-python-client google-auth")
        return None

    creds = service_account.Credentials.from_service_account_info(
        json.loads(creds_json),
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    service = build("drive", "v3", credentials=creds)

    file_name = Path(file_path).name

    # Delete existing file with same name to avoid duplicates
    existing = service.files().list(
        q=f"name='{file_name}' and '{folder_id}' in parents and trashed=false",
        fields="files(id, name)"
    ).execute().get("files", [])
    for f in existing:
        service.files().delete(fileId=f["id"]).execute()
        print(f"  🗑️  Deleted old file: {f['name']}")

    # Upload new file
    file_metadata = {
        "name":    file_name,
        "parents": [folder_id]
    }
    media = MediaFileUpload(
        file_path,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    uploaded = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id,webViewLink"
    ).execute()

    link = uploaded.get("webViewLink", "")
    print(f"  ✅ Uploaded to Drive: {link}")
    return link


# ── STEP 7: Run a single search group ────────────────────

def run_search(
    keyword_groups,
    output_file,
    label="",
    max_results=MAX_RESULTS,
    months_back=1,
):
    query = preview_query(keyword_groups, label=label)
    print(f"\n 📅 Date range : Last {months_back} month(s)")
    print(f" 📦 Max results : {max_results} per source\n")

    pubmed_results  = search_pubmed(query, max_results, months_back)
    scholar_results = search_google_scholar(query, max_results, months_back)
    all_results     = pubmed_results + scholar_results

    if not all_results:
        print(f"\n❌ No articles found for {label}. Try different keywords or a wider date range.")
        return None

    df = pd.DataFrame(all_results, columns=[
        "Status", "Source", "Title", "Abstract", "Publication Year",
        "Journal/Source", "DOI", "PMID", "PubMed URL", "My Comment", "Drive link"
    ])

    # Remove duplicates by title
    before = len(df)
    df.drop_duplicates(subset="Title", keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)
    after = len(df)
    if before != after:
        print(f"\n🧹 Removed {before - after} duplicate(s).")

    save_to_excel(df, output_file, query, months_back)

    print(f"\n✅ Done! {after} articles saved to '{output_file}'")
    print(f" • PubMed        : {len(pubmed_results)} articles")
    print(f" • Google Scholar: {len(scholar_results)} articles")

    return df


# ── STEP 8: Run both groups ───────────────────────────────

if __name__ == "__main__":
    print("\n" + "🟦" * 30)
    print("  Running Search Group 1")
    print("🟦" * 30)
    run_search(
        keyword_groups=KEYWORD_GROUPS_1,
        output_file=OUTPUT_FILE_1,
        label="(Group 1)",
        months_back=MONTHS_BACK_1,
    )

    print("\n" + "🟩" * 30)
    print("  Running Search Group 2")
    print("🟩" * 30)
    run_search(
        keyword_groups=KEYWORD_GROUPS_2,
        output_file=OUTPUT_FILE_2,
        label="(Group 2)",
        months_back=MONTHS_BACK_2,
    )

    print("\n🎉 All done! Both Excel files have been generated.")
