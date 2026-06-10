function testSheetsConnection() {
  const CONFIG = getConfig();
  const ss = SpreadsheetApp.openById(CONFIG.GSHEET_SPREADSHEET_ID);
  Logger.log("✅ Sheets 連線成功：" + ss.getName());

  const tab1 = ss.getSheetByName("Group1");
  const tab2 = ss.getSheetByName("Group2");
  Logger.log("Group1 tab：" + (tab1 ? "✅ 找到，" + (tab1.getLastRow()-1) + " 筆資料" : "❌ 找不到"));
  Logger.log("Group2 tab：" + (tab2 ? "✅ 找到，" + (tab2.getLastRow()-1) + " 筆資料" : "❌ 找不到"));
}

function testGetKeepRows() {
  const CONFIG = getConfig();
  const papers = getKeepRowsFromSheet(CONFIG.GSHEET_SPREADSHEET_ID, "Group1");
  Logger.log("找到 " + papers.length + " 篇 keep");
  papers.forEach(p => {
    Logger.log("  列 " + p.rowIndex + "：" + p.title);
    Logger.log("  DOI：" + (p.doi || "無"));
    Logger.log("  PMID：" + (p.pmid || "無"));
  });
}
function testPdfDownload() {
  const CONFIG = getConfig();
  const papers = getKeepRowsFromSheet(CONFIG.GSHEET_SPREADSHEET_ID, "Group1");

  if (papers.length === 0) {
    Logger.log("❌ 沒有 keep 的論文");
    return;
  }

  const paper = papers[0];
  Logger.log("測試：" + paper.title);
  Logger.log("DOI：" + paper.doi);

  const pdfFileId = downloadPdfToDrive(paper, getConfig().DRIVE_FOLDER_ID);

  if (pdfFileId) {
    Logger.log("✅ PDF 下載成功");
    Logger.log("🔗 https://drive.google.com/file/d/" + pdfFileId + "/view");
  } else {
    Logger.log("⚠️ 找不到 open-access PDF，換一篇有 DOI 的論文試試");
  }
}


function testFullPipeline() {
  const CONFIG = getConfig();
  const papers = getKeepRowsFromSheet(CONFIG.GSHEET_SPREADSHEET_ID, "Group1");

  if (papers.length === 0) {
    Logger.log("❌ 沒有 keep 的論文");
    return;
  }

  const paper = papers[0];
  Logger.log("🚀 全流程測試：" + paper.title);

  try {
    const pdfFileId = downloadPdfToDrive(paper, CONFIG.DRIVE_FOLDER_ID);
    if (!pdfFileId) { Logger.log("❌ PDF 失敗，停止"); return; }

    const driveLink = "https://drive.google.com/file/d/" + pdfFileId + "/view";
    updateSheetStatus(CONFIG.GSHEET_SPREADSHEET_ID, "Group1", paper.rowIndex, "done", driveLink);
    Logger.log("✅ Sheets 回填完成");

    const text    = extractTextFromDrive(pdfFileId);
    const summary = summarizeWithOpenAI(text, CONFIG.OPENAI_API_KEY);
    Logger.log("✅ OpenAI 摘要完成");
    Logger.log("Take-home：" + summary["Take-home message"]);

    writeToNotion(paper.title, summary, CONFIG);
    Logger.log("✅ Notion 寫入完成");

  } catch(e) {
    Logger.log("❌ 錯誤：" + e.message);
  }
}

// ============================================================
// 設定區：從 Script Properties 安全讀取
// ============================================================
function getConfig() {
  const props = PropertiesService.getScriptProperties();
  return {
    OPENAI_API_KEY:        props.getProperty("OPENAI_API_KEY"),
    NOTION_API_KEY:        props.getProperty("NOTION_API_KEY"),
    NOTION_DATABASE_ID:    props.getProperty("NOTION_DATABASE_ID"),
    DRIVE_FOLDER_ID:       props.getProperty("DRIVE_FOLDER_ID"),
    GMAIL_RECIPIENT:       props.getProperty("GMAIL_RECIPIENT"),
    GSHEET_SPREADSHEET_ID: props.getProperty("GSHEET_SPREADSHEET_ID"),
  };
}

// ============================================================
// 主程式：掃 Drive 資料夾內的新 PDF（原有功能，不動）
// ============================================================
function main() {
  const CONFIG = getConfig();
  const processedIds = loadProcessed();
  const newPdfs = listNewPdfs(CONFIG.DRIVE_FOLDER_ID, processedIds);

  if (newPdfs.length === 0) {
    Logger.log("✅ 沒有新論文，結束。");
    return;
  }

  Logger.log(`🔍 發現 ${newPdfs.length} 篇新論文，開始處理...`);
  const newPapersLog = [];
  const xlsxData = loadExcelData();

  for (let i = 0; i < newPdfs.length; i++) {
    const pdf = newPdfs[i];
    Logger.log(`  📖 處理第 ${i + 1}/${newPdfs.length} 篇：${pdf.name}`);

    try {
      const text    = extractTextFromDrive(pdf.id);
      const summary = summarizeWithOpenAI(text, CONFIG.OPENAI_API_KEY);
      writeToNotion(pdf.name.replace(".pdf", ""), summary, CONFIG);
      xlsxData.push({ title: pdf.name.replace(".pdf", ""), ...summary });
      saveProcessed(pdf.id);
      newPapersLog.push({ title: pdf.name.replace(".pdf", ""), summary });
      Logger.log(`  ✅ 完成：${pdf.name}`);
    } catch (e) {
      Logger.log(`  ❌ 失敗：${pdf.name}，錯誤：${e.message}`);
    }

    if (i < newPdfs.length - 1) {
      Logger.log(`  ⏳ 等待 30 秒再處理下一篇...`);
      Utilities.sleep(30000);
    }
  }

  saveExcelToDrive(xlsxData);
  sendGmail(newPapersLog, CONFIG.GMAIL_RECIPIENT);
  Logger.log("🎉 全部完成！");
}

// ============================================================
// ★ 新功能：從 Google Sheets 讀取 keep 的論文 → 下載 PDF
// ============================================================

/**
 * 主入口：讀取 Sheets 中所有標記 keep 的論文
 * 從 DOI 下載 PDF → 上傳 Drive → 回填 Drive link → 執行摘要
 * 在 Apps Script 編輯器手動執行這個函數
 */
function processFromSheets() {
  const CONFIG = getConfig();

  if (!CONFIG.GSHEET_SPREADSHEET_ID) {
    Logger.log("❌ GSHEET_SPREADSHEET_ID 未設定，請到 Script Properties 加入");
    return;
  }

  const tabs = ["Group1", "Group2"];
  const allPapers = [];

  // 讀取兩個 tab 的 keep 論文
  for (const tab of tabs) {
    Logger.log(`\n📋 讀取 Sheets tab：${tab}`);
    const papers = getKeepRowsFromSheet(CONFIG.GSHEET_SPREADSHEET_ID, tab);
    Logger.log(`  找到 ${papers.length} 篇標記 keep`);
    papers.forEach(p => { p.tab = tab; });
    allPapers.push(...papers);
  }

  if (allPapers.length === 0) {
    Logger.log("✅ 沒有標記 keep 的論文，結束。");
    return;
  }

  Logger.log(`\n🚀 開始處理共 ${allPapers.length} 篇論文...`);
  const processedLog = [];

  for (let i = 0; i < allPapers.length; i++) {
    const paper = allPapers[i];
    Logger.log(`\n  📖 第 ${i + 1}/${allPapers.length}：${paper.title}`);

    try {
      // 1. 下載 PDF（透過 DOI → Unpaywall）
      const pdfFileId = downloadPdfToDrive(paper, CONFIG.DRIVE_FOLDER_ID);

      if (!pdfFileId) {
        Logger.log(`  ⚠️ 無法取得 PDF，跳過：${paper.title}`);
        updateSheetStatus(CONFIG.GSHEET_SPREADSHEET_ID, paper.tab, paper.rowIndex, "no_pdf", "");
        continue;
      }

      // 2. 取得 Drive 連結
      const driveLink = `https://drive.google.com/file/d/${pdfFileId}/view`;

      // 3. 回填 Drive link 到 Sheets
      updateSheetStatus(CONFIG.GSHEET_SPREADSHEET_ID, paper.tab, paper.rowIndex, "done", driveLink);

      // 4. 讀取 PDF 文字 → OpenAI 摘要 → 寫入 Notion
      const text    = extractTextFromDrive(pdfFileId);
      const summary = summarizeWithOpenAI(text, CONFIG.OPENAI_API_KEY);
      writeToNotion(paper.title, summary, CONFIG);

      processedLog.push({ title: paper.title, summary });
      Logger.log(`  ✅ 完成：${paper.title}`);

    } catch (e) {
      Logger.log(`  ❌ 失敗：${paper.title}，錯誤：${e.message}`);
      updateSheetStatus(CONFIG.GSHEET_SPREADSHEET_ID, paper.tab, paper.rowIndex, "error", "");
    }

    // 最後一篇不等待
    if (i < allPapers.length - 1) {
      Logger.log(`  ⏳ 等待 30 秒...`);
      Utilities.sleep(30000);
    }
  }

  // 寄摘要通知信
  if (processedLog.length > 0) {
    sendGmail(processedLog, CONFIG.GMAIL_RECIPIENT);
  }

  Logger.log(`\n🎉 processFromSheets 完成！共處理 ${processedLog.length} 篇`);
}

// ============================================================
// ★ 讀取 Sheets：取出 Status = keep 的列
// ============================================================
function getKeepRowsFromSheet(spreadsheetId, tabName) {
  const ss     = SpreadsheetApp.openById(spreadsheetId);
  const sheet  = ss.getSheetByName(tabName);
  if (!sheet) {
    Logger.log(`  ⚠️ 找不到 tab：${tabName}`);
    return [];
  }

  const data    = sheet.getDataRange().getValues();
  const headers = data[0];

  // 找欄位索引（對應 GitHub script 的 COLUMNS）
  const idx = {
    status:    headers.indexOf("Status"),
    title:     headers.indexOf("Title"),
    doi:       headers.indexOf("DOI"),
    pmid:      headers.indexOf("PMID"),
    pubmedUrl: headers.indexOf("PubMed URL"),
    driveLink: headers.indexOf("Drive link"),
    batchDate: headers.indexOf("Batch date"),
  };

  if (idx.status === -1 || idx.title === -1) {
    Logger.log(`  ❌ 找不到 Status 或 Title 欄位，請確認欄位名稱`);
    return [];
  }

  const keepRows = [];
  for (let i = 1; i < data.length; i++) {
    const row    = data[i];
    const status = String(row[idx.status]).trim().toLowerCase();

    // 只處理 keep 且尚未有 Drive link 的列
    if (status === "keep" && !String(row[idx.driveLink] || "").trim()) {
      keepRows.push({
        rowIndex:  i + 1,          // Sheets 列號（1-based，含 header）
        title:     String(row[idx.title]     || "").trim(),
        doi:       String(row[idx.doi]       || "").trim(),
        pmid:      String(row[idx.pmid]      || "").trim(),
        pubmedUrl: String(row[idx.pubmedUrl] || "").trim(),
        batchDate: String(row[idx.batchDate] || "").trim(),
      });
    }
  }

  return keepRows;
}

// ============================================================
// ★ 回填 Sheets：更新 Status 和 Drive link 欄
// ============================================================
function updateSheetStatus(spreadsheetId, tabName, rowIndex, newStatus, driveLink) {
  const ss    = SpreadsheetApp.openById(spreadsheetId);
  const sheet = ss.getSheetByName(tabName);
  if (!sheet) return;

  const headers   = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const statusCol = headers.indexOf("Status")     + 1;  // 轉為 1-based
  const linkCol   = headers.indexOf("Drive link") + 1;

  if (statusCol > 0) sheet.getRange(rowIndex, statusCol).setValue(newStatus);
  if (linkCol   > 0) sheet.getRange(rowIndex, linkCol).setValue(driveLink);

  // 顏色標記
  if (statusCol > 0) {
    const colors = {
      "done":   "#C6EFCE",   // 綠
      "no_pdf": "#FFEB9C",   // 黃
      "error":  "#FFCCCC",   // 紅
      "keep":   "#DDEBF7",   // 藍
    };
    const color = colors[newStatus] || "#FFFFFF";
    sheet.getRange(rowIndex, statusCol).setBackground(color);
  }
}

// ============================================================
// ★ 下載 PDF：DOI → Unpaywall → Drive
// ============================================================
function downloadPdfToDrive(paper, folderId) {
  let pdfUrl = null;

  // 方法 1：透過 DOI 查詢 Unpaywall
  if (paper.doi) {
    pdfUrl = getPdfUrlFromDoi(paper.doi);
    if (pdfUrl) Logger.log(`    🔍 Unpaywall 找到 PDF`);
  }

  // 方法 2：透過 PubMed Central（PMID）
  if (!pdfUrl && paper.pmid) {
    pdfUrl = getPdfUrlFromPmid(paper.pmid);
    if (pdfUrl) Logger.log(`    🔍 PubMed Central 找到 PDF`);
  }

  if (!pdfUrl) {
    Logger.log(`    ⚠️ 找不到 open-access PDF（DOI: ${paper.doi || "無"}）`);
    return null;
  }

  // 下載並存到 Drive
  try {
    const response = UrlFetchApp.fetch(pdfUrl, { muteHttpExceptions: true });
    if (response.getResponseCode() !== 200) {
      Logger.log(`    ❌ PDF 下載失敗，HTTP ${response.getResponseCode()}`);
      return null;
    }

    const blob   = response.getBlob().setName(sanitizeFileName(paper.title) + ".pdf");
    const folder = DriveApp.getFolderById(folderId);
    const file   = folder.createFile(blob);
    Logger.log(`    ✅ PDF 上傳 Drive：${file.getName()}`);
    return file.getId();

  } catch (e) {
    Logger.log(`    ❌ PDF 上傳失敗：${e.message}`);
    return null;
  }
}

// ============================================================
// ★ Unpaywall API：DOI → open-access PDF URL
// ============================================================
function getPdfUrlFromDoi(doi) {
  if (!doi) return null;
  try {
    const url = `https://api.unpaywall.org/v2/${encodeURIComponent(doi)}?email=researcher@example.com`;
    const res = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
    if (res.getResponseCode() !== 200) return null;
    const data = JSON.parse(res.getContentText());
    return data.best_oa_location ? data.best_oa_location.url_for_pdf : null;
  } catch (e) {
    return null;
  }
}

// ============================================================
// ★ PubMed Central：PMID → PDF URL
// ============================================================
function getPdfUrlFromPmid(pmid) {
  if (!pmid) return null;
  try {
    // 查詢 PMC ID
    const url = `https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids=${pmid}&format=json`;
    const res = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
    if (res.getResponseCode() !== 200) return null;
    const data   = JSON.parse(res.getContentText());
    const record = data.records && data.records[0];
    const pmcid  = record ? record.pmcid : null;
    if (!pmcid) return null;

    // PMC PDF URL
    return `https://www.ncbi.nlm.nih.gov/pmc/articles/${pmcid}/pdf/`;
  } catch (e) {
    return null;
  }
}

// ============================================================
// ★ 檔名清理：移除不合法字元
// ============================================================
function sanitizeFileName(name) {
  return name
    .replace(/[\/\\:*?"<>|]/g, "_")
    .replace(/\s+/g, " ")
    .trim()
    .substring(0, 100);  // Drive 檔名上限
}

// ============================================================
// Google Drive：列出新 PDF（原有功能）
// ============================================================
function listNewPdfs(folderId, processedIds) {
  const files    = DriveApp.getFolderById(folderId).getFiles();
  const newFiles = [];
  while (files.hasNext()) {
    const file = files.next();
    if (
      file.getMimeType() === MimeType.PDF &&
      !processedIds.includes(file.getId())
    ) {
      newFiles.push({ id: file.getId(), name: file.getName() });
    }
  }
  return newFiles;
}

// ============================================================
// Google Drive：讀取 PDF 文字（原有功能）
// ============================================================
function extractTextFromDrive(fileId) {
  const file = DriveApp.getFileById(fileId);
  const blob = file.getBlob();

  const resource = {
    title:    "temp_ocr_" + fileId,
    mimeType: MimeType.GOOGLE_DOCS
  };

  const docFile = Drive.Files.create(
    resource,
    blob,
    { ocrLanguage: "en", convert: true }
  );

  const doc  = DocumentApp.openById(docFile.id);
  const text = doc.getBody().getText().substring(0, 20000);  // 從 8000 提升至 20000

  DriveApp.getFileById(docFile.id).setTrashed(true);
  return text;
}

// ============================================================
// OpenAI：產生摘要（更新版 prompt，11 欄位含 Limitation）
// ============================================================
function summarizeWithOpenAI(text, apiKey) {
  const prompt = `You are an infectious disease physician with expertise in clinical AI.
Read the following paper and extract exactly these 11 fields.
Be precise and clinically specific. If a field cannot be determined from the paper, write "Not reported".
Return ONLY a valid JSON object with these exact keys (no markdown, no explanation, no trailing text):
{
  "Background": "Disease/pathogen context, clinical problem being addressed, and geographic setting if stated. 2-3 sentences.",
  "Objective": "State as PICO where possible — Population, Intervention (AI model), Comparator, Outcome. 1-2 sentences.",
  "Methods": "Study design (RCT/retrospective/prospective cohort/etc.), dataset size (n=), data source (EHR/imaging/genomic/claims/surveillance), and validation method (internal/external/cross-validation).",
  "Results": "Key performance metrics with exact numbers: AUC, sensitivity, specificity, F1, accuracy, PPV, NPV — whichever are reported. Include comparator performance if available.",
  "Limitation": "Main methodological weaknesses: selection bias, single-centre, retrospective design, data leakage risk, lack of prospective validation, limited generalisability. 2-3 sentences.",
  "Take-home message": "The single most important clinical finding. Maximum 2 sentences.",
  "AI Task": "One of: diagnosis / prognosis / risk stratification / treatment recommendation / outbreak detection / antimicrobial stewardship / surveillance / other (specify).",
  "Model": "Algorithm name(s) used (e.g. XGBoost, LSTM, transformer, logistic regression). State whether interpretable: yes / no / partial.",
  "Input data": "Data types used as model input (e.g. lab values, vital signs, imaging, genomic sequences, clinical notes, ICD codes). Include sample size.",
  "Output": "What the model produces: classification / risk score / probability / alert / recommendation. State prediction horizon if applicable (e.g. 48h mortality).",
  "Clinical relevance": "Potential clinical application, implementation setting (ICU/ED/outpatient/public health), key barrier to adoption, and whether prospectively validated (yes/no)."
}
Paper:
${text}`;

  const response = UrlFetchApp.fetch(
    "https://api.openai.com/v1/chat/completions",
    {
      method: "POST",
      headers: {
        "Content-Type":  "application/json",
        "Authorization": `Bearer ${apiKey}`
      },
      payload: JSON.stringify({
        model:       "gpt-4o-mini",
        messages:    [{ role: "user", content: prompt }],
        temperature: 0.3
      }),
      muteHttpExceptions: true
    }
  );

  const result = JSON.parse(response.getContentText());
  if (result.error) {
    throw new Error(`OpenAI 錯誤：${result.error.message}`);
  }

  const raw = result.choices[0].message.content
    .replace(/```json|```/g, "")
    .trim();
  return JSON.parse(raw);
}

// ============================================================
// Notion：寫入 Database（更新版，含 Limitation + dedup）
// ============================================================
function notionPageExists(title, CONFIG) {
  const response = UrlFetchApp.fetch(
    `https://api.notion.com/v1/databases/${CONFIG.NOTION_DATABASE_ID}/query`,
    {
      method: "POST",
      headers: {
        "Authorization":  `Bearer ${CONFIG.NOTION_API_KEY}`,
        "Notion-Version": "2022-06-28",
        "Content-Type":   "application/json"
      },
      payload: JSON.stringify({
        filter: { property: "Name", title: { equals: title } }
      }),
      muteHttpExceptions: true
    }
  );
  const result = JSON.parse(response.getContentText());
  return result.results && result.results.length > 0
    ? result.results[0].id
    : null;
}

function writeToNotion(title, summary, CONFIG) {
  const fields = [
    "Background", "Objective", "Methods", "Results", "Limitation",
    "Take-home message", "AI Task", "Model",
    "Input data", "Output", "Clinical relevance", "My Comment"
  ];

  const properties = {
    "Name": { "title": [{ "text": { "content": title } }] }
  };

  fields.forEach(field => {
    properties[field] = {
      "rich_text": [{
        "text": { "content": (summary[field] || "").substring(0, 2000) }
      }]
    };
  });

  const existingId = notionPageExists(title, CONFIG);

  const url     = existingId
    ? `https://api.notion.com/v1/pages/${existingId}`
    : "https://api.notion.com/v1/pages";

  const payload = existingId
    ? { properties }
    : { parent: { database_id: CONFIG.NOTION_DATABASE_ID }, properties };

  const response = UrlFetchApp.fetch(url, {
    method: existingId ? "PATCH" : "POST",
    headers: {
      "Authorization":  `Bearer ${CONFIG.NOTION_API_KEY}`,
      "Notion-Version": "2022-06-28",
      "Content-Type":   "application/json"
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });

  const result = JSON.parse(response.getContentText());
  if (result.status === 400 || result.object === "error") {
    throw new Error(`Notion 錯誤：${result.message}`);
  }
  Logger.log(existingId ? `  🔄 Updated: ${title}` : `  ✨ Created: ${title}`);
}

// ============================================================
// Excel：讀取現有資料（原有功能）
// ============================================================
function loadExcelData() {
  const files = DriveApp.getFilesByName("summaries.csv");
  if (!files.hasNext()) return [];
  const content = files.next().getBlob().getDataAsString();
  const rows    = content.split("\n").slice(1);
  return rows.filter(r => r.trim()).map(r => ({ title: r.split(",")[0] }));
}

// ============================================================
// Excel：儲存 CSV 到 Drive（更新版，含 Limitation）
// ============================================================
function saveExcelToDrive(data) {
  const fields = [
    "Background", "Objective", "Methods", "Results", "Limitation",
    "Take-home message", "AI Task", "Model",
    "Input data", "Output", "Clinical relevance", "My Comment"
  ];

  let csv = ["Title", ...fields].join(",") + "\n";
  data.forEach(row => {
    const values = [
      `"${(row.title || "").replace(/"/g, '""')}"`,
      ...fields.map(f => `"${(row[f] || "").replace(/"/g, '""').replace(/\n/g, " ")}"`)
    ];
    csv += values.join(",") + "\n";
  });

  const oldFiles = DriveApp.getFilesByName("summaries.csv");
  while (oldFiles.hasNext()) oldFiles.next().setTrashed(true);

  DriveApp.createFile("summaries.csv", csv, MimeType.CSV);
  Logger.log("✅ CSV 已儲存到 Google Drive");
}

// ============================================================
// Gmail：寄送摘要（原有功能）
// ============================================================
function sendGmail(newPapers, recipient) {
  if (newPapers.length === 0) return;

  let body = "📄 今日新增論文摘要：\n\n";
  newPapers.forEach(p => {
    body += `【${p.title}】\n`;
    body += `  Background:    ${(p.summary["Background"]      || "").substring(0, 200)}...\n`;
    body += `  Take-home:     ${(p.summary["Take-home message"] || "").substring(0, 200)}...\n`;
    body += `  Limitation:    ${(p.summary["Limitation"]       || "").substring(0, 200)}...\n\n`;
  });

  const files = DriveApp.getFilesByName("summaries.csv");
  if (files.hasNext()) {
    GmailApp.sendEmail(
      recipient,
      `📚 論文摘要更新 - 共 ${newPapers.length} 篇`,
      body,
      { attachments: [files.next().getAs(MimeType.CSV)] }
    );
    Logger.log("✅ Gmail 已寄出");
  }
}

// ============================================================
// 已處理記錄（原有功能）
// ============================================================
function loadProcessed() {
  const props = PropertiesService.getScriptProperties();
  const saved = props.getProperty("processedIds");
  return saved ? JSON.parse(saved) : [];
}

function saveProcessed(fileId) {
  const props   = PropertiesService.getScriptProperties();
  const current = loadProcessed();
  current.push(fileId);
  props.setProperty("processedIds", JSON.stringify(current));
}

function clearProcessedIds() {
  PropertiesService.getScriptProperties().deleteProperty("processedIds");
  Logger.log("✅ Cleared — all PDFs will reprocess on next run");
}

// ============================================================
// 排程設定
// ============================================================
function setupDailyTrigger() {
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger("main")
    .timeBased()
    .atHour(8)
    .everyDays(1)
    .create();
  Logger.log("✅ 每日排程設定完成！每天早上 8 點自動執行");
}
