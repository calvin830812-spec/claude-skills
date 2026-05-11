---
name: urban-renewal-cases-sync
description: 同步並管理本機「臺北市都市更新處 - 都更案件掛件」(https://uro.gov.taipei) 4 大類別 (核定案、公開展覽及公辦公聽會、公辦公聽會發言要點、自辦公聽會) 的公告 PDF 與案件 metadata。Make sure to use this skill whenever the user mentions 同步都更掛件、都更案件公告、都更處最新公告、查詢都更案件、核定案、公開展覽、公辦公聽會、自辦公聽會、發言要點、uro.gov.taipei、台北市都市更新處、看最新有什麼掛件案、查掛件、找某行政區的都更案、找某實施者(建商)的案、找某段某地號的案，即使他們沒明確說「使用 skill」也要觸發。本 skill 也涵蓋對本機 archive 內案件 metadata 的查詢、過濾、按行政區/段/實施者/日期搜尋、案件詳情頁打開、以及將案件相關 PDF 委派 anthropic-skills:pdf 摘要。本 skill 不涵蓋都更案個案開發評估（後者使用 property-eval skill）、都更教育訓練講義同步（後者使用 urban-renewal-handouts-sync skill）、其他都更網站（內政部都更入口等，未來會另起 skill）。注意：該站案件「公告期內限時下架」特性，本 skill 採「看到立即抓快照」策略，落地後就保存。
---

# 臺北市都更處 — 都更案件掛件同步與查詢

寶舖建設集團開發部使用者「穎霖」需要持續監看臺北市都更處公告的掛件案件（核定案、公開展覽、公辦公聽會、自辦公聽會、發言要點），抓回本機保存，方便日後按行政區、段、實施者、地號查詢。**該站檔案有時效性、公告期過了會下架**，所以本 skill 設計為「看到就抓、抓到就永久保留」。

## Archive 結構（固定路徑）

Archive 路徑：`/Users/zhuangyinglin/Library/Mobile Documents/com~apple~CloudDocs/都更知識庫/sources/uro_gov_taipei_cases`

此 archive 是「都更知識庫」(`~/Documents/Claude/Projects/都更知識庫/`) 的子來源之一。整體架構：

```
都更知識庫/
├── sources/
│   ├── uro_clcoordinate_handouts/   # 教育訓練講義 (urban-renewal-handouts-sync skill)
│   └── uro_gov_taipei_cases/         ← 本 skill 管理範圍
│       ├── 核定案/
│       │   ├── pdfs/                 # 命名: YYYY-MM-DD_案名_itemid8_序號.pdf
│       │   └── cases/                # 案件 metadata：itemid.json
│       ├── 公開展覽及公辦公聽會/      (同上結構)
│       ├── 公辦公聽會發言要點/        (此類為 cp.aspx 靜態頁，只有 pdfs/，無 cases/)
│       ├── 自辦公聽會/                (同 案件類)
│       ├── state.json                # 增量基準 (cases + static_pdfs 兩節)
│       ├── index.csv                 # source-level 索引（utf-8-sig，8 欄）
│       ├── index.md                  # 同等資訊 Markdown
│       ├── download_cases.py         # 原版腳本
│       ├── requirements.txt
│       └── .gitignore
├── tools/
│   └── build_master_index.py         # 跨來源 master index 產生器
├── master_index.csv                  # 跨來源統一索引（含 handouts + cases）
└── master_index.md
```

`index.csv` 8 欄 schema：類別、案件序號、公告日期、案件名稱、文件標籤、PDF 本地路徑、PDF 來源連結、詳情頁連結

`cases/<item_id>.json` 內含：item_id、title、list_seq、detail_url、publish_date、body_text（詳情頁原文）、pdfs_meta（每個 PDF 的 label/url/decoded_path）、first_seen 時間。

## Workflow A — 同步掛件（取得最新案件）

當使用者要求同步、或詢問「最近有什麼新掛件」、「都更處有沒有新公告」之類：

1. **執行此 skill 的 `scripts/download_cases.py`**

   ```bash
   python3 "$HOME/.claude/skills/urban-renewal-cases-sync/scripts/download_cases.py"
   ```

   腳本會：
   - 對 4 個類別各做一次抓取（核定案 / 公開展覽 / 發言要點 / 自辦公聽會）
   - 對 News.aspx 類：list page → 對每個案件抓 detail page → 下載 PDF + 存 case JSON
   - 對 cp.aspx 類（發言要點）：直接從 3 欄表格抓 (日期, 案名, PDF)
   - 比對 state.json，只下載新案件 / 新 PDF
   - 下載失敗的會 retry 3 次；下載到的檔案會驗證 PDF magic header（`%PDF`）防止錯誤頁被當 PDF

2. **解讀 stdout 並回報使用者**

   腳本會輸出每類的「小計」與最終的「總結：新增 X / 跳過 Y / 新下載 PDF Z / 失敗」。回報時：
   - 若有新案：列出新案件名稱（從 `[get ]` 行擷取），按類別分組
   - 若 0 新案：回報目前最新狀態（共 N 筆）
   - 若有失敗：列出失敗的 URL/案件名稱

3. **同步完後也跑 master index**（見 Workflow E）

## Workflow B — 查詢 archive（按行政區/段/地號/實施者/日期）

當使用者問「信義區有哪些新掛件」、「找某建商的案」、「列出某段地號的都更案」、「最近 1 個月公告的核定案」之類：

1. **讀 `index.csv` + 必要時讀 `cases/*.json`**

   ```python
   import csv, json
   from pathlib import Path
   ARCHIVE = Path("/Users/zhuangyinglin/Library/Mobile Documents/com~apple~CloudDocs/都更知識庫/sources/uro_gov_taipei_cases")
   with (ARCHIVE / "index.csv").open(encoding="utf-8-sig") as f:
       rows = list(csv.DictReader(f))
   ```

2. **依問題類型過濾（重點：用 `案件名稱` 欄做關鍵字 match，案名通常含 行政區、段、實施者、地號）**

   | 使用者問法 | 過濾邏輯 |
   |-----------|---------|
   | 「信義區的」 | `案件名稱` 含 `信義區` |
   | 「逸仙段三小段 / 雅祥段二小段」（精準段名） | `案件名稱` 含該段名 |
   | 「實施者：潤泰 / 國泰 / 富邦」 | `案件名稱` 含該公司名（建商名通常在「○○股份有限公司擔任實施者」前） |
   | 「核定案」/「自辦公聽會」/「公開展覽」 | `類別` 等於該值 |
   | 「最近 30 天」 | `公告日期` 在 today - 30 之內 |
   | 「2026 年 4 月」 | `公告日期.startswith("2026-04")` |
   | 「權利變換計畫」/「事業計畫」 | `案件名稱` 含該關鍵字 |

3. **回應格式**

   按 `公告日期` 反向排序、條列回應，每筆含：
   - 公告日期、類別、案件名稱（截 80 字）
   - PDF 本地路徑（用 markdown link）
   - 詳情頁連結（指向 uro.gov.taipei，使用者可在瀏覽器查看完整資訊）

   範例：
   ```
   找到 3 筆「信義區」相關掛件：
   - 2026-04-29 [核定案] 公告核定實施立樺建設...信義區逸仙段三小段766地號等14筆... [PDF](pdfs/...) ・[詳情頁](https://uro.gov.taipei/News_Content.aspx?...)
   - 2026-04-13 [自辦公聽會] 公告_遠雄建設...信義區雅祥段三小段14...
   ```

4. **若使用者要更深的查詢（複合條件 / 全文搜尋）**

   讀 `cases/*.json`（每個案件有 body_text + pdfs_meta），用 Python 過濾。例如：
   ```python
   for case_file in (ARCHIVE / "核定案/cases").glob("*.json"):
       case = json.loads(case_file.read_text(encoding="utf-8"))
       if "信義" in case["title"] and "權利變換" in case["title"]:
           ...
   ```

## Workflow C — 摘要單一案件 / 多案件比較

若使用者要求「幫我看看 X 案在講什麼」、「比較 A/B 兩個案的差異」：

1. 用 Workflow B 找到對應 PDF
2. 確認本地檔存在
3. 委派 `anthropic-skills:pdf` skill 讀取並摘要
4. 摘要建議聚焦於穎霖開發部觀點：基地概況（區位、面積、地號）、實施者、建蔽率/容積率、權利變換條件、公告期限與下個關鍵時點、與寶舖既有案件的比較啟發

## Workflow D — 監看「即將過期 / 公告中」的案件

掛件公告有時效性。當使用者問「有什麼快過期 / 還在公告期的案」：

1. 讀 `index.csv`
2. 計算每筆 `公告日期` 與當前日期差距
3. 一般公告期 30 天為基準（實際依案件類型不同），列出 30 天內的案件

## Workflow E — 重建跨來源 master index

當使用者問「都更知識庫現在共有多少資料」、「列出所有來源」、「跨來源查詢」：

```bash
python3 "$HOME/.claude/skills/urban-renewal-cases-sync/scripts/build_master_index.py"
```

或直接：
```bash
python3 "/Users/zhuangyinglin/Library/Mobile Documents/com~apple~CloudDocs/都更知識庫/tools/build_master_index.py"
```

會讀取 `sources/*/index.csv` 並重建 `master_index.csv` + `master_index.md`。每次 sync 完都建議跑一次。

## 不該做的事

- **不要**自己寫 BeautifulSoup 重新爬 uro.gov.taipei — 用 `scripts/download_cases.py` 即可
- **不要**修改命名規則 — `YYYY-MM-DD_標題截斷_itemid8.pdf` 是約定，state.json 與 index 都依此
- **不要**幫使用者跑「定時同步 cron」— 公告頻率約 1-3 天一筆，使用者隨時觸發更靈活
- **不要**對「快過期」案件過度緊張、催促使用者 — 平實列出時間點即可

## 該站特性備註

- 4 個類別 list 頁面預設顯示最新 10 筆（公開展覽 / 核定案）或最新 25-26 筆（自辦公聽會），目前實測無分頁控制 — 即「最新 N 筆」就是可見全部
- 公辦公聽會發言要點 (cp.aspx) 是長期累積靜態表格（目前 72 列），不是「最新公告」性質
- 案件詳情頁的 body_text 通常很短（80-150 字），主要是 title 重複；真正的內容在 PDF 裡
- PDF 託管在 `https://www-ws.gov.taipei/Download.ashx?u=<base64>` 或直接 `https://www-ws.gov.taipei/001/Upload/...` — 兩種都會被腳本偵測為 PDF
- 注意：`laws.gov.taipei` 是 HTML 法規查詢站（不是 PDF），腳本已過濾掉

## 與其他 skill 的邊界

- **property-eval**（都更案個案開發評估）：當使用者要評估投報、住戶分回、建商獲利、基地配置 — 那是 property-eval 的範疇。本 skill 是「公告檔案管理」，property-eval 是「案件試算」。例：「幫我評估這塊地能不能做都更」→ property-eval；「找出 X 段地號最近的掛件公告」→ 本 skill
- **urban-renewal-handouts-sync**：教育訓練講義同步。例：「估價講義有哪幾份」→ handouts；「估價師看的某都更案是哪個」→ 本 skill
- **anthropic-skills:pdf**：本 skill 在 Workflow C 委派給它做 PDF 摘要、提取條款
- **anthropic-skills:xlsx**：若使用者要把 `index.csv` 加工成正式報表（標色、樞紐、圖表）— 本 skill 出原料、xlsx skill 負責加工
