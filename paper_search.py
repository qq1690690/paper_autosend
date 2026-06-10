# paper_search.py
# ============================================================
# 📚 Article Search Tool — Google Scholar + PubMed
# Two independent keyword groups → one Google Sheets file
# (Group1 tab + Group2 tab), cumulative append
# ============================================================

import os
import json
import time
import datetime
import requests
import pandas as pd
# scholarly 改為延遲載入，避免 CI import 時卡住


# ── STEP 1: 🔑 CONFIG ─────────────────────────────────────

# --- Search Group 1 ---
KEYWORD_GROUPS_1 = [
    {"keywords": ["infectious disease", "infection control", "infection prevention and control", "antimicrobial stewardship"], "logic": "OR"},
    {"keywords": ["machine learning", "generative AI", "Large language model"], "logic": "OR"},
]
SHEET_TAB_1 = "Group1"

# --- Search Group 2 ---
KEYWORD_GROUPS_2 = [
    {"keywords": ["crhvkp", "carbapenem resistant hypervirulent klebsiella pneumoniae", "hypervirulent klebsiella pneumoniae"], "logic": "OR"},
    {"keywords": ["clinical outcome"], "logic": "AND"},
]
SHEET_TAB_2 = "Group2"

# Keep xlsx output for email attachment
OUTPUT_FILE_1 = "articles_group1.xlsx"
OUTPUT_FILE_2 = "articles_group2.xlsx"

MAX_RESULTS   = 50
MONTHS_BACK_1 = 1
MONTHS_BACK_2 = 12

PUBMED_MAX_RETRIES = 3
PUBMED_RETRY_DELAY = 5
SCHOLAR_MAX_ERRORS = 3

# Column order — shared across all functions
COLUMNS = [
    "Status", "Source", "Title", "Abstract", "Publication Year",
    "Journal/Source", "DOI", "PMID", "PubMed URL", "My Comment", "Drive link"
]


# ── STEP 2: Build query string ────────────────────────────

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


# ── STEP 3: Search PubMed ─────────────────────────────────

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

    search_params = {
        "db":       "pubmed",
        "term":     query,
        "retmax":   max_results,
        "mindate":  start_date.strftime("%Y/%m/%d"),
        "maxdate":  end_date.strftime("%Y/%m/%d"),
        "datetype": "pdat",
        "retmode":  "json",
    }

    try:
        resp = _requests_get_with_retry(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            search_params
        )
        ids = resp.json().get("esearchresult", {}).get("idlist", [])
    except Exception as e:
        print(f" ❌ PubMed search failed, skipping: {e}")
        return results

    if not ids:
        print(" ⚠️ No PubMed results found for this date range.")
        return results

    print(f" ✅ Found {len(ids)} PubMed IDs — fetching details...")

    import xml.etree.ElementTree as ET

    for i in range(0, len(ids), 20):
        batch = ids[i:i+20]
        try:
            r = _requests_get_with_retry(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                {"db": "pubmed", "id": ",".join(batch), "retmode": "xml", "rettype": "abstract"}
            )
            root = ET.fromstring(r.text)
        except Exception as e:
            print(f" ❌ Failed to fetch batch {i//20 + 1}, skipping: {e}")
            continue

        for article in root.findall(".//PubmedArticle"):
            try:
                title    = article.findtext(".//ArticleTitle") or ""
                abstract = " ".join(a.text or "" for a in article.findall(".//AbstractText"))
                year     = (article.findtext(".//PubDate/Year") or
                            article.findtext(".//PubDate/MedlineDate", "")[:4])
                journal  = (article.findtext(".//Journal/Title") or
                            article.findtext(".//MedlineTA") or "")
                pmid     = article.findtext(".//PMID") or ""
                doi_elem = article.find(".//ArticleId[@IdType='doi']")
                doi      = doi_elem.text.strip() if doi_elem is not None else ""

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


# ── STEP 4: Search Google Scholar (local only) ────────────

def search_google_scholar(query, max_results=50, months_back=1):
    # ── 延遲載入：只在本機執行時才 import，CI 不會碰到 ──
    try:
        from scholarly import scholarly as _scholarly
    except ImportError:
        print(" ❌ scholarly not installed, skipping Google Scholar.")
        return []

    print("🔍 Searching Google Scholar...")
    results = []

    cutoff_year = (datetime.datetime.now() - datetime.timedelta(days=30 * months_back)).year
    consecutive_errors = 0

    try:
        search_query = _scholarly.search_pubs(query)
        count = 0
        while count < max_results:
            try:
                pub      = next(search_query)
                bib      = pub.get("bib", {})
                year_str = str(bib.get("pub_year", ""))

                if year_str:
                    try:
                        if int(year_str) < cutoff_year:
                            continue
                    except ValueError:
                        pass

                doi = bib.get("doi", "") or pub.get("externalIds", {}).get("DOI", "") or ""

                results.append({
                    "Status":           "unread",
                    "Source":           "Google Scholar",
                    "Title":            bib.get("title", "").strip(),
                    "Abstract":         bib.get("abstract", "").strip(),
                    "Publication Year": year_str.strip(),
                    "Journal/Source":   (bib.get("venue", "") or bib.get("journal", "")).strip(),
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
                    print(f" ❌ Google Scholar blocked: {e}")
                    break
                print(f" ⚠️ Skipped one result ({consecutive_errors}/{SCHOLAR_MAX_ERRORS}): {e}")
                if consecutive_errors >= SCHOLAR_MAX_ERRORS:
                    print(f" ❌ Too many consecutive errors, stopping Scholar search.")
                    break
                time.sleep(2)

    except Exception as e:
        print(f" ❌ Google Scholar error: {e}")
        print(" ℹ️  Continuing with PubMed results only.")

    print(f" ✅ Retrieved {len(results)} results from Google Scholar.")
    return results


# ── STEP 5: AI Prescreening ───────────────────────────────

def ai_prescreening(papers, api_key=None):
    from openai import OpenAI

    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("⚠️  OPENAI_API_KEY not set, skipping AI prescreening.")
        return papers

    client = OpenAI(api_key=api_key)
    screened = []

    for i, paper in enumerate(papers):
        title    = paper.get("Title", "")
        abstract = paper.get("Abstract", "")

        if not title:
            screened.append(paper)
            continue

        prompt = (
            "You are an expert physician reviewer. Evaluate whether this paper is relevant and worth keeping.\n"
            'Criteria for "keep": original research on AI/ML applied to infectious disease or infection control, with clear clinical relevance.\n'
            'Criteria for "skip": review articles, letters, editorials, unrelated topics, or very low methodological quality.\n\n'
            'Return ONLY a JSON object: {"decision": "keep" or "skip", "reason": "one sentence"}\n\n'
            f"Title: {title}\n"
            f"Abstract: {abstract[:1000]}"
        )

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            raw = response.choices[0].message.content.strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            result = json.loads(raw)
            decision = result.get("decision", "unread").lower()
            if decision not in ("keep", "skip"):
                decision = "unread"
            paper = {**paper, "Status": decision}
            print(f"  [{i+1}/{len(papers)}] {decision.upper()} — {title[:70]}")
        except Exception as e:
            print(f"  ⚠️ AI screening failed for paper {i+1}: {e}")

        screened.append(paper)

    keeps = sum(1 for p in screened if p.get("Status") == "keep")
    skips = sum(1 for p in screened if p.get("Status") == "skip")
    print(f"\n🤖 AI Prescreening done: {keeps} keep, {skips} skip, {len(screened)-keeps-skips} unread")
    return screened


# ── STEP 6: Save to Excel (for email attachment) ──────────

def save_to_excel(df, output_file, query, months_back):
    from openpyxl import load_workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    df.to_excel(output_file, index=False, engine="openpyxl")
    wb = load_workbook(output_file)
    ws = wb.active

    header_fill = PatternFill("solid", fgColor="4472C4")
    header_font = Font(bold=True, color="FFFFFF")
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    col_widths = {
        "A": 12, "B": 15, "C": 55, "D": 80, "E": 12,
        "F": 35, "G": 35, "H": 14, "I": 42, "J": 22, "K": 42,
    }
    for col, width in col_widths.items():
        ws.column_dimensions[col].width = width

    for row in ws.iter_rows(min_row=2, min_col=4, max_col=4):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    status_colors = {"keep": "C6EFCE", "skip": "FFCCCC", "unread": "FFFFFF"}
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=1):
        for cell in row:
            color = status_colors.get(str(cell.value).strip().lower(), "FFFFFF")
            cell.fill = PatternFill("solid", fgColor=color)
            cell.alignment = Alignment(horizontal="center", vertical="center")

    ws_note = wb.create_sheet("Search Info")
    ws_note["A1"], ws_note["B1"] = "Search Query", query
    ws_note["A2"], ws_note["B2"] = "Date Range", f"Last {months_back} month(s)"
    ws_note["A3"], ws_note["B3"] = "Run Date", datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    ws_note["A4"], ws_note["B4"] = "Total Articles", len(df)

    wb.save(output_file)
    print(f" ✅ Excel saved: {output_file}")


# ── STEP 6: Append to Google Sheets ──────────────────────

def append_to_sheets(df, sheet_tab, run_date=None):
    import json

    creds_json     = os.environ.get("GDRIVE_CREDENTIALS")
    spreadsheet_id = os.environ.get("GSHEET_SPREADSHEET_ID")

    if not creds_json or not spreadsheet_id:
        print("⚠️  GDRIVE_CREDENTIALS or GSHEET_SPREADSHEET_ID not set, skipping Sheets upload.")
        return

    try:
        from googleapiclient.discovery import build
        from google.oauth2 import service_account
    except ImportError:
        print("❌ google-api-python-client not installed.")
        return

    creds = service_account.Credentials.from_service_account_info(
        json.loads(creds_json),
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=creds)
    sheet   = service.spreadsheets()

    if run_date is None:
        run_date = datetime.datetime.now().strftime("%Y-%m-%d")

    # Read existing titles for deduplication (column C = Title)
    try:
        result = sheet.values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_tab}!C:C"
        ).execute()
        existing_values = result.get("values", [])
    except Exception:
        existing_values = []

    existing_titles = set(
        row[0].strip().lower()
        for row in existing_values[1:]
        if row
    )

    headers = ["Batch date"] + COLUMNS

    # Write header if sheet is empty
    try:
        first_cell = sheet.values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_tab}!A1"
        ).execute()
        has_header = bool(first_cell.get("values"))
    except Exception:
        has_header = False

    if not has_header:
        sheet.values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_tab}!A1",
            valueInputOption="RAW",
            body={"values": [headers]}
        ).execute()
        print(f" ✅ Header written to tab '{sheet_tab}'")

    # Filter duplicates and build rows
    new_rows = []
    skipped  = 0
    for _, row in df.iterrows():
        title = str(row.get("Title", "")).strip().lower()
        if title in existing_titles:
            skipped += 1
            continue
        new_rows.append(
            [run_date] + [str(row.get(col, "")) for col in COLUMNS]
        )

    if skipped:
        print(f" ℹ️  Skipped {skipped} duplicate title(s)")

    if not new_rows:
        print(f" ℹ️  No new rows to append to tab '{sheet_tab}'")
        return

    sheet.values().append(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_tab}!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": new_rows}
    ).execute()

    print(f" ✅ Appended {len(new_rows)} new row(s) to Sheets tab '{sheet_tab}'")


# ── STEP 7: Run a single search group ────────────────────

def run_search(
    keyword_groups,
    output_file,
    sheet_tab,
    label="",
    max_results=MAX_RESULTS,
    months_back=1,
):
    query    = preview_query(keyword_groups, label=label)
    run_date = datetime.datetime.now().strftime("%Y-%m-%d")

    print(f"\n 📅 Date range : Last {months_back} month(s)")
    print(f" 📦 Max results : {max_results} per source\n")

    # ── PubMed (always runs) ──
    pubmed_results = search_pubmed(query, max_results, months_back)

    # ── Google Scholar (skip in CI via env var or if not installed) ──
    skip_scholar = os.environ.get("SKIP_SCHOLAR", "false").lower() == "true"
    if skip_scholar:
        print("ℹ️  Google Scholar skipped (SKIP_SCHOLAR=true)")
        scholar_results = []
    else:
        scholar_results = search_google_scholar(query, max_results, months_back)

    all_results = pubmed_results + scholar_results

    if not all_results:
        print(f"\n❌ No articles found for {label}.")
        return None

    print(f"\n🤖 Running AI prescreening on {len(all_results)} articles...")
    all_results = ai_prescreening(all_results)

    df = pd.DataFrame(all_results, columns=COLUMNS)

    before = len(df)
    df.drop_duplicates(subset="Title", keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)
    after = len(df)
    if before != after:
        print(f"\n🧹 Removed {before - after} duplicate(s) within batch.")

    save_to_excel(df, output_file, query, months_back)

    print(f"\n📤 Appending to Google Sheets tab '{sheet_tab}'...")
    append_to_sheets(df, sheet_tab, run_date)

    print(f"\n✅ Done! {after} articles processed for {label}")
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
        sheet_tab=SHEET_TAB_1,
        label="(Group 1)",
        months_back=MONTHS_BACK_1,
    )

    print("\n" + "🟩" * 30)
    print("  Running Search Group 2")
    print("🟩" * 30)
    run_search(
        keyword_groups=KEYWORD_GROUPS_2,
        output_file=OUTPUT_FILE_2,
        sheet_tab=SHEET_TAB_2,
        label="(Group 2)",
        months_back=MONTHS_BACK_2,
    )

    print("\n🎉 All done!")
