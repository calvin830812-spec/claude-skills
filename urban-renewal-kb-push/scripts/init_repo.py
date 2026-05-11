#!/usr/bin/env python3
"""
都更知識庫 — 首次推 GitHub 初始化腳本

行為：
1. 檢查 gh CLI 是否已裝 + 已登入
2. 寫入 .gitignore（排除公開計畫書大檔）
3. git init -b main
4. git add -A + 首次 commit
5. gh repo create calvin830812-spec/urban-renewal-kb --public --source=. --remote=origin --push

可用環境變數 URO_KB_DIR 覆蓋預設知識庫路徑。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_KB = "/Users/zhuangyinglin/Library/Mobile Documents/com~apple~CloudDocs/都更知識庫"
KB_ROOT = Path(os.environ.get("URO_KB_DIR", DEFAULT_KB)).expanduser().resolve()

GH_REPO = "calvin830812-spec/urban-renewal-kb"
GH_VISIBILITY = "--public"

GITIGNORE = """\
# 大型公開計畫書（>100MB，超過 GitHub 單檔上限）
sources/uro_gis_taipei_plans/pdfs/**/*公開計畫書*.pdf

# 系統 / 暫存檔
.DS_Store
__pycache__/
*.pyc
.ipynb_checkpoints/
*.icloud
"""


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=str(KB_ROOT), check=False, **kw)


def main() -> int:
    print(f"KB root: {KB_ROOT}")
    if not KB_ROOT.exists():
        print(f"[error] 找不到知識庫目錄：{KB_ROOT}")
        return 1

    # --- 1. 檢查 gh CLI ---
    print("\n=== 1. 檢查 gh CLI ===")
    if not shutil.which("gh"):
        print("[stop] gh CLI 未安裝。請先在終端機跑：")
        print("       brew install gh")
        print("       gh auth login")
        print("       完成後再重跑本 skill。")
        return 2

    auth = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if auth.returncode != 0:
        print("[stop] gh 未登入。請跑：")
        print("       gh auth login")
        return 2
    print("  gh CLI 已裝且已登入")

    # --- 2. 寫 .gitignore ---
    print("\n=== 2. 寫入 .gitignore ===")
    gi = KB_ROOT / ".gitignore"
    if gi.exists():
        print(f"  .gitignore 已存在，覆寫")
    gi.write_text(GITIGNORE, encoding="utf-8")
    print(f"  寫入：{gi}")

    # --- 3. git init ---
    print("\n=== 3. git init ===")
    if (KB_ROOT / ".git").exists():
        print("  .git 已存在，跳過 init（本應改跑 sync_push.py）")
    else:
        r = run(["git", "init", "-b", "main"])
        if r.returncode != 0:
            print("[error] git init 失敗")
            return 3

    # --- 4. add + first commit ---
    print("\n=== 4. 首次 commit ===")
    run(["git", "add", "-A"])

    # 統計各來源檔案數
    counts = {}
    for src in ["uro_gov_taipei_cases", "uro_gis_taipei_plans", "uro_clcoordinate_handouts"]:
        sd = KB_ROOT / "sources" / src
        if sd.exists():
            # 用 git diff --cached 算實際 staged 數
            r = subprocess.run(
                ["git", "diff", "--cached", "--name-only", "--", f"sources/{src}"],
                cwd=str(KB_ROOT), capture_output=True, text=True
            )
            counts[src] = len([l for l in r.stdout.splitlines() if l.strip()])
        else:
            counts[src] = 0

    msg = (
        f"init: urban renewal knowledge base — "
        f"cases:{counts['uro_gov_taipei_cases']} "
        f"plans:{counts['uro_gis_taipei_plans']} "
        f"handouts:{counts['uro_clcoordinate_handouts']}"
    )
    r = run(["git", "commit", "-m", msg])
    if r.returncode != 0:
        print("[warn] commit 失敗（可能沒有檔案要 commit，或 git user 未設定）")
        # 檢查 git user
        cfg_email = subprocess.run(["git", "config", "user.email"],
                                    cwd=str(KB_ROOT), capture_output=True, text=True)
        if not cfg_email.stdout.strip():
            print("[stop] git user.email 未設定。請跑：")
            print('       git config --global user.email "calvin830812@gmail.com"')
            print('       git config --global user.name "calvin830812-spec"')
            return 4

    # --- 5. gh repo create ---
    print("\n=== 5. gh repo create + push ===")
    # 檢查 remote 是否已存在
    rm = subprocess.run(["git", "remote"], cwd=str(KB_ROOT), capture_output=True, text=True)
    if "origin" in rm.stdout.split():
        print("  origin remote 已存在，跳過 gh repo create，直接 push")
        r = run(["git", "push", "-u", "origin", "main"])
    else:
        r = run([
            "gh", "repo", "create", GH_REPO,
            GH_VISIBILITY, "--source=.", "--remote=origin", "--push"
        ])

    if r.returncode != 0:
        print("[error] 推送失敗。請看上面錯誤訊息。")
        return 5

    print("\n========== 完成 ==========")
    print(f"Repo URL: https://github.com/{GH_REPO}")
    print("下次跑 skill 會走 Workflow B（例行同步）→ scripts/sync_push.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
