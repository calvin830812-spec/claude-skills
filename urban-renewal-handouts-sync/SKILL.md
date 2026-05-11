---
name: urban-renewal-handouts-sync
description: 同步並管理本機「臺北市都市再生教育訓練 - 下載專區」(http://uro.clcoordinate.com/pgDownload.aspx) 的講義 PDF 檔案庫。Make sure to use this skill whenever the user mentions 同步都更講義、下載專區有沒有新的、都更教育訓練 PDF / 講義、都更講座 / 自主更新培訓班 / 都更解壓說系列課程、uro.clcoordinate、臺北市都更教育訓練、都更講義索引、查詢已下載的都更講義（例如「有沒有估價相關的講義？」「列出 4 月份下載的都更講義」「找出某講師的講義」「都更解壓說系列我有哪幾集」），即使他們沒明確說「使用 skill」也要觸發。本 skill 也涵蓋對本機 archive 內容的查詢、過濾、排序與摘要委派。本 skill 不涵蓋一般 PDF 下載 / 一般網站爬蟲 / 其他都更網站（內政部都更入口、中央都更案例庫等），也不涵蓋都更案個案開發評估（後者使用 property-eval skill）。
---

# 臺北市都更教育訓練講義同步與查詢

寶舖建設集團開發部使用者「穎霖」需要定期同步臺北市都更處發布的教育訓練講義（網站本身免費公開），並能在本機 archive 中按主題、日期、講師、課程系列查找特定講義。

## Archive 結構（固定路徑）

Archive 路徑：`/Users/zhuangyinglin/Library/Mobile Documents/com~apple~CloudDocs/都更知識庫/sources/uro_clcoordinate_handouts`

此 archive 是「都更知識庫」(`~/Documents/Claude/Projects/都更知識庫/`) 的子來源之一。其他來源（uro_gov_taipei_cases 等）位於同階。整體架構：

```
都更知識庫/
├── sources/
│   ├── uro_clcoordinate_handouts/   ← 本 skill 管理範圍
│   │   ├── pdfs/                    # 講義 PDF：YYYY-MM-DD_課程名稱.pdf
│   │   ├── index.csv                # source-level 索引（utf-8-sig，6 欄）
│   │   ├── index.md                 # 同等資訊 Markdown
│   │   ├── state.json               # 增量基準（key = PDF 來源 URL）
│   │   ├── download.py              # 原版腳本（與本 skill scripts/download.py 等價）
│   │   └── requirements.txt
│   └── uro_gov_taipei_cases/        # 都更案掛件，由 urban-renewal-cases-sync skill 管理
├── master_index.csv                 # 跨來源統一索引
└── master_index.md
```

`index.csv` 是查詢 archive 的單一真相來源 — 用 Python `csv` 讀取，不要嘗試解析 `index.md`。

## Workflow A — 同步講義（取得最新）

當使用者要求同步、或詢問「有沒有新的」、「最近更新了嗎」之類：

1. **執行此 skill 內建的 `scripts/download.py`**

   ```bash
   python3 "$HOME/.claude/skills/urban-renewal-handouts-sync/scripts/download.py"
   ```

   腳本內建將下載目錄指向固定 archive 路徑，無須額外參數。腳本會：
   - 對 `--All--` 主頁做 GET，解析 RadGrid，得到最新清單（目前約 10 筆）
   - 對 4 個分類各做一次 ASP.NET `__doPostBack`，建立分類對應
   - 比對 `state.json`，僅下載新增的 PDF 至 `pdfs/`
   - 改名為 `YYYY-MM-DD_課程名稱.pdf`
   - 重寫 `index.csv` 與 `index.md`

2. **解讀 stdout 並回報使用者**

   腳本最後一行格式：`總結：新增 X / 跳過 Y / 失敗 Z`

   - `X > 0`：列出 stdout 中所有 `[get ] ...` 行對應的課程名稱，告訴使用者新增了哪幾筆
   - `X == 0`：告訴使用者目前已是最新狀態（共 Y 筆）
   - `Z > 0`：列出失敗的檔案，建議稍後重試

3. **失敗排查**

   | 症狀 | 原因 | 處理 |
   |------|------|------|
   | `parse rows = 0`、`找不到任何課程資料` | 該站 HTML 結構改版 | 提示使用者該站改版，需更新 `parse_rows()` selector |
   | requests timeout 連續失敗 | 網路問題或該站暫時不可達 | 建議稍後再跑 |
   | `__VIEWSTATE` 取不到 | 該站可能換框架 | 需要重新檢查 ASP.NET hidden fields |
   | 單一 PDF 下載失敗（其他正常） | 該檔案暫時不可達 | 重跑即可重試（state 沒被寫入該 URL） |

## Workflow B — 查詢 archive 內容

當使用者問「我有沒有 X 的講義」、「列出 X 月份的」、「找出 X 講師」、「X 系列我有哪幾集」：

1. **讀 `index.csv`（不是 `index.md`）**

   ```python
   import csv
   from pathlib import Path
   ARCHIVE = Path("/Users/zhuangyinglin/Documents/Claude/Projects/抓網站上的都更檔案下載")
   with (ARCHIVE / "index.csv").open(encoding="utf-8-sig") as f:
       rows = list(csv.DictReader(f))
   # rows[i] 有欄位: 日期, 課程名稱, 分類, PDF 本地路徑, PDF 來源連結, YouTube 連結
   ```

2. **依問題類型過濾**

   | 使用者問法 | 過濾邏輯 |
   |-----------|---------|
   | 「估價相關」/「估價師」 | `課程名稱` 含 `估價` |
   | 「4 月份的」/「4 月講義」 | `日期.startswith("YYYY-04")`，年份用今年（看當下日期） |
   | 「黃健峯」/「某講師」 | `課程名稱` 含 `_講師名` 或結尾為 `_講師名` |
   | 「都更講座」 | `課程名稱.startswith("都更講座")` |
   | 「自主更新培訓班」 | `課程名稱.startswith("自主更新培訓班")` |
   | 「都更解壓說」 | `課程名稱.startswith("都更解壓說")` |
   | 「最近的」/「新的」 | 依 `日期` 反向排序，取前 5 筆 |
   | 「有影音的」 | `YouTube 連結` 非空 |

   檔案路徑變化：之前在 `抓網站上的都更檔案下載/` 的 archive 已遷移到 `sources/uro_clcoordinate_handouts/`。所有 `index.csv` 中的 `PDF 本地路徑` 為相對於 archive 根的路徑（例 `pdfs/2026-05-09_xxx.pdf`），實際解析時前綴 archive 路徑即可。

3. **回應格式**

   條列式，含日期、課程名稱、PDF 本地路徑（用 markdown link 讓使用者可點擊）；如有 YouTube 也附上。範例：

   ```
   找到 4 筆「估價」相關講義：
   - 2026-04-10 [都更解壓說01.都更估價師在估什麼？_鐘少佑](pdfs/2026-04-10_都更解壓說01...pdf) ・ [▶ YouTube](https://...)
   - 2026-04-10 [都更解壓說02.花百萬裝潢有加分嗎？...連琳育](pdfs/2026-04-10_都更解壓說02...pdf)
   ```

## Workflow C — 摘要單一講義

若使用者要求「幫我摘要 X 講義」、「這份在講什麼」、「重點整理」：

1. 用 Workflow B 找到對應 PDF 路徑
2. 確認檔案存在
3. 呼叫 `anthropic-skills:pdf` skill 讀取並摘要
4. 摘要時優先考量穎霖的工作角度（寶舖建設開發部、主導建案專案開發）：講師觀點、適用場景、對都更案實務的啟發、可直接應用於協議合建/權變案的要點

## Workflow D — 列出 archive 統計概況

若使用者問「目前有幾份講義」、「archive 摘要」、「都更講義總覽」：

1. 讀 `index.csv`，輸出：
   - 總筆數
   - 課程系列分布（依名稱前綴分組）
   - 日期範圍（最早 → 最新）
   - 有影音連結 vs 純講義的數量
   - 最近 3 筆新增

## 不該做的事

- **不要**自己寫 BeautifulSoup 重新爬該網站 — 用 `scripts/download.py` 即可，它已處理 ASP.NET viewstate
- **不要**改檔名規則 — `YYYY-MM-DD_課程名稱.pdf` 是約定，state.json 與 index 都依此
- **不要**建議使用者用 cron 自動排程 — 該站更新頻率低（約每月 1-2 次），手動觸發更省資源
- **不要**幫使用者下載 YouTube 影片 — 索引留連結即可，影片不在 scope

## 該站特性備註

- 4 個分類（專業者 / 一般民眾 / 大專院校 / 自主更新）目前後台被全標記，所以分類欄常顯示「全部」。日後若該站精修分類，腳本會自動以「、」串接顯示，不需要改 code
- PDF 直連 base URL 為 `http://urbanredev.clcoordinate.com/uploadedFiles/`（注意是 urbanredev 子網域，不是 uro 子網域）
- 該站目前無分頁（`AllowPaging:false`），`--All--` 一頁取得全部資料

## 與其他 skill 的邊界

- **property-eval**（都更案個案評估）：當使用者談地號、容積率、建商獲利率、銷容比、權利變換、住戶分回 — 那是 property-eval 的範疇，不要走本 skill
- **anthropic-skills:pdf**：本 skill 在 Workflow C 委派給它做 PDF 摘要與內容問答
- **anthropic-skills:xlsx**：若使用者要把 `index.csv` 轉成正式報表或統計表格 — 本 skill 列清單即可，加工部分交給 xlsx skill
