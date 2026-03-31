# paper_search.py
# ============================================================
# 📚 Article Search Tool — Google Scholar + PubMed
# Two independent keyword groups → two separate Excel files
# ============================================================

import time
import datetime
import requests
import pandas as pd
from scholarly import scholarly


# ── STEP 1: 🔑 CONFIG ─────────────────────────────────────

# --- Search Group 1 ---
KEYWORD_GROUPS_1 = [
    {"keywords": ["infectious disease", "infection control"], "logic": "OR"},
    {"keywords": ["machine learning", "generative AI"], "logic": "OR"},
]
OUTPUT_FILE_1 = "articles_group1.xlsx"

# --- Search Group 2 ---
# Original PubMed query:
#   ((crhvkp AND (y_5[Filter])) OR (carbapenem resistant hypervirulent klebsiella pneumoniae AND (y_5[Filter])))
#   AND (clinical outcome AND (y_5[Filter]))
# Note: y_5[Filter] (past 5 years) is handled by MONTHS_BACK for PubMed date range;
#       Google Scholar uses keywords only without PubMed-specific filters.
KEYWORD_GROUPS_2 = [
    {"keywords": ["crhvkp", "carbapenem resistant hypervirulent klebsiella pneumoniae"], "logic": "OR"},
    {"keywords": ["clinical outcome"], "logic": "AND"},
]
OUTPUT_FILE_2 = "articles_group2.xlsx"

MAX_RESULTS = 50      # Max results per source (20–50)
MONTHS_BACK_1 = 1     # Group 1: last N months
MONTHS_BACK_2 = 12    # Group 2: last N months (past 1 year)


# ── STEP 2: Build query string from groups ────────────────

def build_query(groups):
    """
    Joins keywords within each group by their specified logic (AND/OR),
    then joins all groups together with AND.
    """
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

def search_pubmed(query, max_results=50, months_back=1):
    print("\n🔍 Searching PubMed...")
    results = []

    end_date = datetime.datetime.now()
    start_date = end_date - datetime.timedelta(days=30 * months_back)
    mindate = start_date.strftime("%Y/%m/%d")
    maxdate = end_date.strftime("%Y/%m/%d")

    search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    search_params = {
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "mindate": mindate,
        "maxdate": maxdate,
        "datetype": "pdat",
        "retmode": "json",
    }
    resp = requests.get(search_url, params=search_params, timeout=15)
    ids = resp.json().get("esearchresult", {}).get("idlist", [])

    if not ids:
        print(" ⚠️ No PubMed results found for this date range.")
        return results

    print(f" ✅ Found {len(ids)} PubMed IDs — fetching details...")

    fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    import xml.etree.ElementTree as ET

    for i in range(0, len(ids), 20):
        batch = ids[i:i+20]
        fetch_params = {
            "db": "pubmed",
            "id": ",".join(batch),
            "retmode": "xml",
            "rettype": "abstract",
        }
        r = requests.get(fetch_url, params=fetch_params, timeout=15)
        root = ET.fromstring(r.text)

        for article in root.findall(".//PubmedArticle"):
            try:
                title = article.findtext(".//ArticleTitle") or ""
                abstract_parts = article.findall(".//AbstractText")
                abstract = " ".join(a.text or "" for a in abstract_parts)
                year = article.findtext(".//PubDate/Year") or \
                       article.findtext(".//PubDate/MedlineDate", "")[:4]
                journal = article.findtext(".//Journal/Title") or \
                          article.findtext(".//MedlineTA") or ""
                results.append({
                    "Source": "PubMed",
                    "Title": title.strip(),
                    "Abstract": abstract.strip(),
                    "Publication Year": year.strip(),
                    "Journal/Source": journal.strip(),
                })
            except Exception as e:
                print(f" ⚠️ Skipped one article: {e}")
        time.sleep(0.4)

    return results


# ── STEP 4: Search Google Scholar ────────────────────────

def search_google_scholar(query, max_results=50, months_back=1):
    print("🔍 Searching Google Scholar...")
    results = []
    cutoff_year = (datetime.datetime.now() - datetime.timedelta(days=30 * months_back)).year

    try:
        search_query = scholarly.search_pubs(query)
        count = 0
        while count < max_results:
            try:
                pub = next(search_query)
                bib = pub.get("bib", {})
                year = str(bib.get("pub_year", ""))

                if year and int(year) < cutoff_year:
                    continue

                title = bib.get("title", "")
                abstract = bib.get("abstract", "")
                journal = bib.get("venue", "") or bib.get("journal", "")

                results.append({
                    "Source": "Google Scholar",
                    "Title": title.strip(),
                    "Abstract": abstract.strip(),
                    "Publication Year": year.strip(),
                    "Journal/Source": journal.strip(),
                })
                count += 1
                time.sleep(1.2)

            except StopIteration:
                break
            except Exception as e:
                print(f" ⚠️ Skipped one result: {e}")
                time.sleep(2)

    except Exception as e:
        print(f" ❌ Google Scholar error: {e}")
        print(" Tip: If you see a CAPTCHA error, try again after a few minutes.")

    print(f" ✅ Retrieved {len(results)} results from Google Scholar.")
    return results


# ── STEP 5: Save results to styled Excel ─────────────────

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

    col_widths = {"A": 15, "B": 50, "C": 80, "D": 18, "E": 35}
    for col, width in col_widths.items():
        ws.column_dimensions[col].width = width

    for row in ws.iter_rows(min_row=2, min_col=3, max_col=3):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

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

    wb.save(output_file)


# ── STEP 6: Run a single search group ────────────────────

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

    pubmed_results = search_pubmed(query, max_results, months_back)
    scholar_results = search_google_scholar(query, max_results, months_back)
    all_results = pubmed_results + scholar_results

    if not all_results:
        print(f"\n❌ No articles found for {label}. Try different keywords or a wider date range.")
        return None

    df = pd.DataFrame(all_results, columns=[
        "Source", "Title", "Abstract", "Publication Year", "Journal/Source"
    ])

    # Remove duplicates
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


# ── STEP 7: Run both groups ───────────────────────────────

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
