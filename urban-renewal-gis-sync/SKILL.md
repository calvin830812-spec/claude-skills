---
name: urban-renewal-gis-sync
description: 同步並管理本機「臺北市都更雲端 GIS」(https://gis.uro.taipei) 上的「公告公文 PDF」與「公開計畫書 PDF」。種子來自 sources/uro_gov_taipei_cases 的掛件案件清單，自動轉成 (行政區, 段, 母號, 子號) 查 GIS，找到對應案件後抓 r_progress_detail 內部 case_id，呼叫 Get_project168_top/eighth/ten ashx 取得 metadata 與 PDF 清單，再透過 DownloadODFile.ashx 下載。Make sure to use this skill whenever the user mentions 都更雲端、gis.uro.taipei、都更審議服務平台、都更案計畫書、公開計畫書、公告公文、府都新字、案件進度查詢、r_progress_detail、ODrecords、依地號找計畫書、依段找事業計畫書、依實施者找計畫書、抓計畫書 PDF，即使沒明確說「使用 skill」也要觸發。本 skill 不涵蓋都更案個案開發評估（後者使用 property-eval）、教育訓練講義（urban-renewal-handouts-sync）、都更處掛件公告本身（urban-renewal-cases-sync）。本 skill 與 urban-renewal-cases-sync 互補：cases-sync 抓「公告本文」(uro.gov.taipei)，本 skill 抓「實際計畫書 PDF」(gis.uro.taipei)。
---

# 臺北市都更雲端 GIS — 公告公文與公開計畫書同步

寶舖建設集團開發部使用者「穎霖」已透過 `urban-renewal-cases-sync` 抓回 `uro.gov.taipei` 上的公告本文 (1–3 頁通知)，但「真正的事業計畫、權利變換計畫、公展計畫書本體」是託管在 `gis.uro.taipei` 上的另一套 ASP.NET AJAX 系統。本 skill 補上這塊缺口。

## Archive 結構（固定路徑）

Archive 路徑：`/Users/zhuangyinglin/Library/Mobile Documents/com~apple~CloudDocs/都更知識庫/sources/uro_gis_taipei_plans`

```
都更知識庫/
├── sources/
│   ├── uro_clcoordinate_handouts/    # 教育訓練講義 (urban-renewal-handouts-sync)
│   ├── uro_gov_taipei_cases/          # 公告本文掛件 (urban-renewal-cases-sync)
│   └── uro_gis_taipei_plans/          ← 本 skill 管理範圍
│       ├── cases/                     # 一個案件一個 JSON：{internal_case_id}.json
│       ├── pdfs/
│       │   └── {行政區}/              # 行政區次層分類
│       │       └── {YYYY-MM-DD}_{case_id}_{subject}_{原檔名}.pdf
│       ├── state.json                 # 增量基準
│       ├── index.csv                  # 8 欄索引（與 cases-sync 同 schema）
│       ├── index.md
│       ├── download_gis_plans.py      # 主腳本
│       ├── requirements.txt
│       └── .gitignore
├── tools/
│   └── build_master_index.py          # 已含 uro_gis_taipei_plans profile
├── master_index.csv
└── master_index.md
```

`index.csv` 8 欄：類別、案件序號、公告日期、案件名稱、文件標籤、PDF 本地路徑、PDF 來源連結、詳情頁連結

`cases/{internal_case_id}.json` 內含：case_id、external_case_id、case_name、district、executor、place、details_url、top_meta（公展開始日 / 各階段日期 / 實施者）、od_pdfs 清單、ten_pdfs 清單、first_seen / last_seen。

## GIS 系統 API 一覽（已驗證可運作）

| Endpoint | Method | Params | 用途 |
|---|---|---|---|
| `ashx/Get_updcase_list.ashx` | POST | `qitem=qland&sectstr={段}&monobuf={母號}&sunobuf={子號}` | 案件清單 |
| `ashx/get_project168_top.ashx` | POST | `case_id={internal}` | 案件 header |
| `ashx/Get_project168_eighth.ashx` | POST | `case_id={internal}` | 公告公文 PDF list |
| `ashx/Get_project168_ten.ashx` | POST | `case_id={internal}&type=get` | 公開計畫書 list (公展期才有) |
| `ashx/DownloadODFile.ashx` | GET | `filename={...}` | 下載 PDF 本體 |

**關鍵：** `Get_updcase_list` 回傳的 `details` 欄位有兩種：
- `ua_frmEasyCase.aspx?case_id=...` → 自行劃定核准單元，**無計畫書文件**，跳過
- `r_progress_detail.aspx?case_id={內部 id}` → **進入此分支才有計畫書**；URL 中的內部 id 才是 168 系列 endpoint 用的 case_id

## Workflow A — 同步公告公文與公開計畫書（種子驅動）

當使用者要求同步、或詢問「最近有什麼新計畫書」、「都更雲端有沒有新文件」之類：

1. **執行此 skill 的 `scripts/download_gis_plans.py`**

   ```bash
   python3 "$HOME/.claude/skills/urban-renewal-gis-sync/scripts/download_gis_plans.py"
   ```

   或執行 archive 內的版本（兩者同步）：

   ```bash
   python3 "/Users/zhuangyinglin/Library/Mobile Documents/com~apple~CloudDocs/都更知識庫/sources/uro_gis_taipei_plans/download_gis_plans.py"
   ```

   腳本會：
   - 讀 `sources/uro_gov_taipei_cases/index.csv` 抽 (行政區, 段, 母號, 子號) 種子
   - 對每個種子查 `Get_updcase_list.ashx`
   - 過濾出 `details` 含 `r_progress_detail` 的案件，取出內部 case_id
   - 對每個 unique 內部 case_id：
     - `get_project168_top.ashx` → 案件 header (案名/實施者/位置)
     - `Get_project168_eighth.ashx` → 公告公文清單 → 下載每個 PDF
     - `Get_project168_ten.ashx` → 公開計畫書清單 → **預設只記 metadata**
   - 比對 state.json，已下載的檔案略過
   - 公告公文 PDF 通常 200KB-1MB，全量下載安全
   - 公開計畫書 PDF (ten) **單檔 100MB-500MB**，預設只記 metadata；要下載需設環境變數：

   ```bash
   URO_GIS_DOWNLOAD_PLAN_BOOKS=1 python3 "$HOME/.claude/skills/urban-renewal-gis-sync/scripts/download_gis_plans.py"
   ```

   或針對特定案件單獨下載 (見 Workflow D)

2. **解讀 stdout 並回報**

   ```
   ========== 總結 ==========
   處理種子數: 106
   案件: 新增 X / 已知 Y / 失敗 Z
   公告公文 PDF: 新下載 N1 / 略過 M1 / 失敗 F1
   公開計畫書 PDF: 新下載 N2 / 略過 M2 / 失敗 F2
   ```

3. **同步完後跑 master index**（見 Workflow E）

## Workflow B — 查詢 archive（按行政區/段/實施者/案名）

```python
import csv, json
from pathlib import Path
ARCHIVE = Path("/Users/zhuangyinglin/Library/Mobile Documents/com~apple~CloudDocs/都更知識庫/sources/uro_gis_taipei_plans")
with (ARCHIVE / "index.csv").open(encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

# 例：找信義區的所有 PDF
xinyi = [r for r in rows if "信義區" in r["案件名稱"]]
```

更深的 metadata（含 top 各階段日期、實施者）：

```python
for case_file in (ARCHIVE / "cases").glob("*.json"):
    case = json.loads(case_file.read_text(encoding="utf-8"))
    if "信義區" in case["case_name"] and "潤泰" in case.get("executor", ""):
        ...
```

| 使用者問法 | 過濾邏輯 |
|---|---|
| 「信義區計畫書」 | `案件名稱` 含 `信義區` |
| 「實施者：潤泰／國泰」 | 讀 `cases/*.json`，比對 `executor` |
| 「公展中的案件」 | `類別` 為 `公開計畫書`（ten_pdfs 來源） |
| 「最近公告」 | `公告日期` 倒序 |
| 「事業計畫書」/「權利變換」 | `案件名稱` 含關鍵字 |

回應建議：每筆列出 公告日期、文件主題（subject + 文號）、案名截 60 字、PDF 本地路徑、詳情頁連結（`https://gis.uro.taipei/r_progress_detail.aspx?case_id=...`）。

## Workflow C — 摘要單一計畫書

1. Workflow B 找到目標 PDF
2. 委派 `anthropic-skills:pdf` skill 讀取
3. 摘要建議聚焦穎霖開發部觀點：
   - 基地概況（位置 PLACE、面積、地號）
   - 實施者
   - 容積率 / 建蔽率 / 樓地板面積
   - 權利變換條件（共同負擔比例、分回比例）
   - 公展期限與下個關鍵時點
   - 與寶舖既有案件比較

## Workflow D — 下載特定案件的公開計畫書本體

公開計畫書 (ten) 單檔常 100MB-500MB，預設只記 metadata。當使用者明確要看某案的計畫書時：

1. **查到目標案件的內部 case_id** (從 index.csv 或 state.json)：
   - 例：「大安區金華段四小段126」 → state.json 有 cases 10010111, 10010112

2. **直接呼叫 download endpoint**（先確認 ten metadata 有東西可下載）：

   ```python
   import json, requests
   from pathlib import Path
   ARCHIVE = Path("/Users/zhuangyinglin/Library/Mobile Documents/com~apple~CloudDocs/都更知識庫/sources/uro_gis_taipei_plans")
   case_id = "11408002"  # 換成目標
   case = json.loads((ARCHIVE / "cases" / f"{case_id}.json").read_text(encoding="utf-8"))
   for pdf in case.get("ten_pdfs", []):
       load = pdf["load_name"]
       fname = pdf["filename"]
       url = f"https://gis.uro.taipei/ashx/Get_project168_ten.ashx?type=download&load_name={load}&case_id={case_id}"
       dest = ARCHIVE / "pdfs" / case["district"] / f"{pdf['exhibit_start']}_{case_id}_公開計畫書_{fname[:40]}.pdf"
       dest.parent.mkdir(parents=True, exist_ok=True)
       with requests.get(url, stream=True, timeout=600) as r:
           with open(dest, "wb") as f:
               for c in r.iter_content(65536): f.write(c)
       print(f"saved {dest} ({dest.stat().st_size//1024//1024}MB)")
   ```

3. **直接以 (段, 母號) 查 GIS** 當尚未在 archive 時：

   ```python
   from sources.uro_gis_taipei_plans.download_gis_plans import search_cases, extract_internal_case_id
   import requests
   s = requests.Session()
   results = search_cases(s, "金華段四小段", "126", "0")
   for case in results:
       cid = extract_internal_case_id(case.get("details", ""))
       if cid:
           print(cid, case.get("schedule"), case.get("case_name", "")[:40])
   ```

4. 若該地號 GIS 也找不到，建議使用者改查 [地政局新舊地建號查詢](https://w2.land.gov.taipei/LBN/NOLB_V100.aspx)（地號可能已分割合併）。

## Workflow E — 重建跨來源 master index

```bash
python3 "/Users/zhuangyinglin/Library/Mobile Documents/com~apple~CloudDocs/都更知識庫/tools/build_master_index.py"
```

會讀取 `sources/*/index.csv` 並重建 `master_index.csv` + `master_index.md`，包含三個來源（handouts + cases + plans）。每次 sync 完都建議跑一次。

## 不該做的事

- **不要**自己寫 BeautifulSoup 重新爬 gis.uro.taipei — GIS 是純 AJAX，腳本已用正確的 ashx endpoint
- **不要**修改命名規則 — `{date}_{case_id}_{subject}_{filename}` 是 state.json 的對照鍵
- **不要**對 `ua_frmEasyCase.aspx` 分支案件嘗試抓計畫書 — 那分支沒有 168 系列文件
- **不要**幫使用者跑「全 12 行政區 × 全段」sweep — 腳本目前刻意只走種子，避免暴力查詢
- **不要**跑定時 cron — 公告頻率不高、使用者手動觸發即可

## 與其他 skill 的邊界

- **urban-renewal-cases-sync**：抓 uro.gov.taipei 公告本文。本 skill 抓 gis.uro.taipei 計畫書本體。先跑 cases-sync（產生種子），再跑本 skill。
- **urban-renewal-handouts-sync**：抓教育訓練講義，與本 skill 無交集
- **property-eval**（個案開發評估）：本 skill 出檔案，property-eval 做試算
- **anthropic-skills:pdf**：本 skill 在 Workflow C 委派給它
- **anthropic-skills:xlsx**：若使用者要把 `index.csv` 加工成正式報表
