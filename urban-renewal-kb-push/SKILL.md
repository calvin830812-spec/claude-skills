---
name: urban-renewal-kb-push
description: 把本機「都更知識庫」(/Users/zhuangyinglin/Library/Mobile Documents/com~apple~CloudDocs/都更知識庫/) 推送到 GitHub repo `calvin830812-spec/urban-renewal-kb`，**自動排除超過 100MB 的公開計畫書 PDF**（檔名含「公開計畫書」字串）。Make sure to use this skill whenever the user mentions 推到 GitHub、推上去、同步到 GitHub、備份知識庫、把都更知識庫推到雲端、push knowledge base、sync 完推、把資料庫推到 github、把檔案推到 git、備份到 git 上面、即使他們沒明確說「使用 skill」也要觸發。本 skill 是 sync 系列（urban-renewal-cases-sync / urban-renewal-gis-sync / urban-renewal-handouts-sync）的「下一步」：使用者跑完任一同步後，呼叫本 skill 把新增/更新的成果推到 GitHub。本 skill **不涵蓋**：抓取資料（用對應 sync skill）、評估個案（property-eval）、PDF 摘要（anthropic-skills:pdf）。本 skill 也不會自動安裝 gh CLI、不會 force-push、不會用 git lfs、不會修改下載腳本或 master_index 內容。
---

# 都更知識庫 — 推送到 GitHub

寶舖建設集團開發部使用者「穎霖」每次跑完 sync skill（如 `urban-renewal-cases-sync`）抓到新資料後，希望把成果推到 GitHub 做版本管理與雲端備份。

## 知識庫路徑與目標 repo

- **本機根目錄**：`/Users/zhuangyinglin/Library/Mobile Documents/com~apple~CloudDocs/都更知識庫/`
- **GitHub repo**：`calvin830812-spec/urban-renewal-kb`（public）
- **Repo URL**：https://github.com/calvin830812-spec/urban-renewal-kb

## 為什麼要排除「公開計畫書」

GIS 來源的「公開計畫書」單檔通常 100MB-500MB（檔名含 `公開計畫書` 字串），共約 22 個檔、佔 sources/uro_gis_taipei_plans/pdfs/ 6.8GB 中絕大多數。
- 超過 GitHub **單檔 100MB 上限**
- 不適合 git history（推 LFS 也會吃配額）
- 本機已有檔即可，GitHub 只需 metadata（state.json/index.csv/index.md）就能還原案件清單

排除 pattern（寫在 .gitignore）：
```
sources/uro_gis_taipei_plans/pdfs/**/*公開計畫書*.pdf
```

其他 PDF（公展、核定公告等小檔，數百 KB）全部進 git。

## Workflow A — 首次初始化（偵測到 `.git` 不存在時）

當使用者要求推送，本機 `都更知識庫/.git/` 又不存在時：

1. **跑 init 腳本**

   ```bash
   python3 "$HOME/.claude/skills/urban-renewal-kb-push/scripts/init_repo.py"
   ```

   腳本會：
   - 檢查 `gh` CLI 是否已裝 + 登入。若沒裝 → **列出指令請使用者自己跑**（不擅自 `brew install`）：
     ```
     brew install gh
     gh auth login
     ```
     然後請使用者重跑本 skill。
   - 寫入 `.gitignore`（包含計畫書排除、系統暫存檔規則）
   - `git init -b main`
   - `git add -A` → 首次 commit（訊息：`init: urban renewal knowledge base — cases:N plans:N handouts:N`）
   - 跑 `gh repo create calvin830812-spec/urban-renewal-kb --public --source=. --remote=origin --push`

2. **解讀 stdout 並回報**
   - repo URL
   - 推送了幾個 file、跳過幾個（被 .gitignore match）
   - 提示「下次跑這個 skill 就會走 Workflow B（例行同步）」

## Workflow B — 例行同步（已 init 的情況）

當使用者跑完 sync skill 後，要求把成果推上去：

1. **跑 sync 腳本**

   ```bash
   python3 "$HOME/.claude/skills/urban-renewal-kb-push/scripts/sync_push.py"
   ```

   腳本會：
   - 偵測 iCloud placeholder 檔（`*.icloud`）→ 若有就停下提醒使用者觸發下載
   - 跑 `git status --short` 收集變動
   - 跑 `find . -size +99M -not -path "./.git/*" -not -name "*.icloud"` 大檔安全網。**若有意外大檔 → 印出檔名後停下問使用者**，不自動加入 .gitignore
   - 變動按來源分組顯示（cases / plans / handouts / 其他）
   - 若無變動 → 印「無變動可推」乾淨結束
   - 否則：`git add -A` → `git commit -m "sync: YYYY-MM-DD — cases:+N plans:+N handouts:+N"` → `git push`
   - push 失敗（網路、衝突）→ 停下回報，**絕不 force-push**

2. **解讀 stdout 並回報**
   - 本次推送幾個 file、commit hash、repo URL
   - 若有 placeholder 或大檔警告 → 列出檔名供使用者處理

## 不該做的事

- ❌ **不要 force-push** — 衝突時停下問使用者，never `--force` / `-f`
- ❌ **不要用 `git lfs`** — 大計畫書直接排除即可，不要用 LFS（會佔配額）
- ❌ **不要擅自跑 `brew install`** — 列出指令請使用者自己跑
- ❌ **不要自動跑 sync skill** — sync 的責任在對應 sync skill，本 skill 只負責 push
- ❌ **不要修改 `master_index.csv`、`master_index.md`、下載腳本** — 那是其他 skill 的範疇
- ❌ **不要改 `_公開計畫書_` 命名規則** — 這是 sync skill 約定的字串，本 skill 只 match 不改
- ❌ **不要把意外的大檔（>99MB 非計畫書）自動加進 .gitignore** — 印出檔名讓使用者決定

## 觸發節奏

本 skill 設計為使用者主動觸發，預期節奏：
- 跑完任一 sync skill 後立即推一次
- 或每週末整批同步後推一次

不需要設定 cron / 自動排程；穎霖隨時觸發更靈活。

## 與其他 skill 的邊界

- **urban-renewal-cases-sync / urban-renewal-gis-sync / urban-renewal-handouts-sync**：負責抓資料。本 skill 是它們的「下一步」。例：「同步都更掛件 + 推到 GitHub」→ 先跑 cases-sync，再跑本 skill。
- **property-eval**：個案投報試算。本 skill 不涉及。
- **anthropic-skills:pdf**：PDF 摘要。本 skill 不涉及。

## SKILL.md 內定參數

- `KB_ROOT="/Users/zhuangyinglin/Library/Mobile Documents/com~apple~CloudDocs/都更知識庫"`
- `GH_REPO="calvin830812-spec/urban-renewal-kb"`
- `GH_VISIBILITY="--public"`
- 排除 pattern：`sources/uro_gis_taipei_plans/pdfs/**/*公開計畫書*.pdf`
