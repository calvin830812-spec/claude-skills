---
name: urban-renewal-kb-routine
description: 「都更知識庫」例行更新 SOP — 一次跑完整套流程：① cases sync（掛件公告，GIS 種子來源）→ ② GIS sync（公告公文 + 公開計畫書）→ ③ handouts sync（教育訓練講義）→ ④ master_index 跨來源彙整 → ⑤ 跨來源核對（state vs index、PDF 落地、iCloud placeholder）→ ⑥ 推 GitHub 備份。Make sure to use this skill whenever the user mentions 例行更新、做今天的更新、跑一輪同步、整套同步、SOP 跑一遍、都更知識庫更新、跑完整流程、週末更新一下、把這次的資料都同步好、依序執行、執行步驟、整理資料、抓檔案的流程，即使他們沒明確說「使用 skill」也要觸發。本 skill 是「指揮者」，不重抓資料，**只負責編排各既有 skill 的執行順序、檢查依賴、核對結果、回報總結**。本 skill 不涵蓋：個案開發評估（用 property-eval）、PDF 摘要（用 anthropic-skills:pdf）、單純查詢已有資料（用對應 sync skill 的查詢 Workflow）、設定 cron 自動排程（穎霖手動觸發更靈活）。
---

# 都更知識庫 — 例行更新 SOP（標準作業程序）

寶舖建設集團開發部「穎霖」每隔一段時間（週末 / 整批清整時）跑一輪整套知識庫更新。各來源 sync skill 已經獨立存在，但**單跑某一個容易忘掉後續步驟**（master_index 沒重建、新檔沒推 GitHub、跨來源依賴沒檢查）。本 skill 把這些綁成固定順序的 SOP。

## 為什麼要一條龍

| 漏掉的步驟 | 會出什麼問題 |
|------|------|
| 先 GIS 後 cases | GIS 的種子（行政區、段、地號）來自 cases index — 漏新案 |
| 跑完忘了 master_index | 跨來源查詢落後實際內容、Claude 答錯 |
| 不核對 | 計畫書 metadata 有但 PDF 沒下載成功，使用者以為有但點開沒檔 |
| 推 GitHub 前沒看 iCloud placeholder | 推到一半遇到佔位符，推出壞檔 |

固定順序消除這些風險：**cases → GIS → handouts → master_index → 核對 → push**。

## 知識庫架構（給 Claude 快速 mental model）

```
~/Library/Mobile Documents/com~apple~CloudDocs/都更知識庫/
├── sources/
│   ├── uro_gov_taipei_cases/         ← 掛件公告（uro.gov.taipei）
│   │   ├── 核定案/、公開展覽.../、公辦公聽會發言要點/、自辦公聽會/
│   │   ├── state.json、index.csv、index.md
│   │   └── download_cases.py
│   ├── uro_gis_taipei_plans/          ← 公告公文 + 公開計畫書（gis.uro.taipei）
│   │   ├── pdfs/{行政區}/             ← 命名: YYYY-MM-DD_case_id_類別_標題.pdf
│   │   ├── cases/{case_id}.json
│   │   ├── state.json、index.csv、index.md
│   │   └── download_gis_plans.py
│   └── uro_clcoordinate_handouts/     ← 教育訓練講義（uro.clcoordinate.com）
│       ├── pdfs/、state.json、index.csv、index.md
│       └── download_handouts.py
├── tools/
│   └── build_master_index.py          ← 跨來源彙整器
├── master_index.csv、master_index.md  ← 跨來源統一索引
└── .gitignore、.git/                  ← GitHub 備份用（urban-renewal-kb-push）
```

index.csv 統一 10 欄：`類別、案件序號、掛件時間、行政區、建設公司、案件名稱、文件標籤、PDF 本地路徑、PDF 來源連結、詳情頁連結`

## 標準執行流程

### Step 1：cases sync（先做，是 GIS 的種子來源）

委派 `urban-renewal-cases-sync` skill 跑 Workflow A：
```bash
python3 "$HOME/.claude/skills/urban-renewal-cases-sync/scripts/download_cases.py"
```

抓 4 類掛件公告：核定案 / 公開展覽 / 公辦公聽會發言要點 / 自辦公聽會。每類僅抓「最新可見 N 筆」，重複案會 skip。

**完成後記錄**：本步驟新增 X 筆 / 新下載 PDF Y 個。

### Step 2：GIS sync（從 cases 抽種子）

委派 `urban-renewal-gis-sync` skill：
```bash
python3 "$HOME/.claude/skills/urban-renewal-gis-sync/scripts/download_gis_plans.py"
```

從 Step 1 的 cases index 解析 (行政區, 段, 母號, 子號) 當種子，到 gis.uro.taipei 查 case_id，下載公告公文 PDF + 公開計畫書 metadata（計畫書本體預設只記 metadata，因為單檔 100-500MB；設 `URO_GIS_DOWNLOAD_PLAN_BOOKS=1` 才下載）。

**完成後記錄**：新增 X 案件 / 新下載 Y 個 PDF。

### Step 3：handouts sync（獨立來源，跟 cases / GIS 無依賴）

委派 `urban-renewal-handouts-sync` skill：
```bash
python3 "$HOME/.claude/skills/urban-renewal-handouts-sync/scripts/download_handouts.py"
```

順序可前可後，放這裡只是把「3 個下載」連在一起。

**完成後記錄**：新增 X 份講義。

### Step 4：master_index 跨來源彙整

```bash
python3 "/Users/zhuangyinglin/Library/Mobile Documents/com~apple~CloudDocs/都更知識庫/tools/build_master_index.py"
```

讀 `sources/*/index.csv` 合成 master_index.csv + master_index.md。各 sync skill 內可能已跑過，本 SOP 保險再跑一次，確保 master_index 反映最新狀態。

### Step 5：跨來源核對

跑本 skill 自帶的 verify 腳本：
```bash
python3 "$HOME/.claude/skills/urban-renewal-kb-routine/scripts/verify.py"
```

檢查項目：
- 各來源 `state.json` 案件數 vs `index.csv` 列數是否對齊
- GIS / cases 的 PDF `local_path` 是否實際存在於本機
- 是否有 iCloud `.icloud` placeholder（影響後續推 GitHub）
- 各來源最新一筆的日期
- 三個來源的總筆數

若有異常（漏檔、placeholder）→ **印出問題列表，停下問使用者要不要繼續推**。

### Step 6：推 GitHub 備份

委派 `urban-renewal-kb-push` skill：
- 若 `.git` 不存在 → 走 init flow（要求 `brew install gh && gh auth login`）
- 若 `.git` 存在 → 走 sync_push flow

完成後記錄：commit hash + 推送檔案數。

### Step 7：總結回報

格式範例：
```
都更知識庫 例行更新 完成 — 2026-05-11
=====================================
Step 1 cases:        +0 / 共 127  ✅
Step 2 GIS:          +0 案件 / +0 PDF  ✅
Step 3 handouts:     +0 / 共 10  ✅
Step 4 master_index: 1,434 筆已重建 ✅
Step 5 核對:         ✅ 全對齊
Step 6 GitHub:       無變動可推 / commit abc1234 推送成功
```

## 中途中斷的處理

若任一 Step 出錯：
1. 印出錯誤訊息與失敗的 URL / 檔名
2. **停下，不接續下一步**
3. 等使用者決定：重試 / 跳過此步驟 / 中止

特別是 Step 1 失敗 → 不要跑 Step 2（種子缺，會抓不到新案）。

## 不該做的事

- ❌ **不要跳過 cases 直接跑 GIS** — 種子會缺
- ❌ **不要平行跑 sync** — 各 skill 內已有 rate limiting，平行會踩到對方 / 觸發網站擋
- ❌ **不要在有 iCloud placeholder 時硬推** — 會推到佔位符
- ❌ **不要把本 SOP 設成 cron 自動排程** — 穎霖手動觸發、看核對結果再決定推不推
- ❌ **不要在本 skill 內重新實作各 sync skill 的邏輯** — 只編排呼叫
- ❌ **不要在 Step 4 / Step 5 / Step 6 失敗時繼續往下推** — 看核對結果決定

## 何時用本 skill vs 單一 skill

| 情境 | 用哪個 |
|------|------|
| 「今天來更新一下」「跑一輪同步」「整套同步」 | **本 SOP** |
| 「看最近有什麼新掛件」（純查詢，不更新） | urban-renewal-cases-sync 查詢 Workflow |
| 「下載專區有沒有新講義」（單一來源） | urban-renewal-handouts-sync 直接 |
| 「找某地號的計畫書」（查詢） | urban-renewal-gis-sync 查詢 Workflow |
| 「推到 GitHub」（單純推、不重抓） | urban-renewal-kb-push 直接 |
| 「評估某都更案」 | property-eval |

## SKILL.md 內定參數

- `KB_ROOT="/Users/zhuangyinglin/Library/Mobile Documents/com~apple~CloudDocs/都更知識庫"`
- 委派的 sync skill：`urban-renewal-cases-sync`、`urban-renewal-gis-sync`、`urban-renewal-handouts-sync`
- 委派的 push skill：`urban-renewal-kb-push`
- 跨來源核對腳本：`$HOME/.claude/skills/urban-renewal-kb-routine/scripts/verify.py`
