#!/usr/bin/env python3
"""
都更知識庫 — 例行同步推 GitHub

行為：
1. 偵測 iCloud placeholder 檔（*.icloud）→ 若有就停下提醒
2. git status 收集變動，按來源分組顯示
3. 大檔安全網：find -size +99M（非計畫書、非 .git）→ 若有意外大檔，停下問使用者
4. git add -A + commit + push
5. 絕不 force-push；衝突就停下回報

支援 --dry-run：只看會發生什麼，不動 git。

可用環境變數 URO_KB_DIR 覆蓋預設知識庫路徑。
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_KB = "/Users/zhuangyinglin/Library/Mobile Documents/com~apple~CloudDocs/都更知識庫"
KB_ROOT = Path(os.environ.get("URO_KB_DIR", DEFAULT_KB)).expanduser().resolve()

PLAN_BOOK_MARKER = "公開計畫書"  # 排除 pattern 已在 .gitignore，這裡只是安全網用的字串


def run(cmd: list[str], capture: bool = False) -> subprocess.CompletedProcess:
    if not capture:
        print(f"  $ {' '.join(cmd)}")
    return subprocess.run(
        cmd, cwd=str(KB_ROOT), check=False,
        capture_output=capture, text=True
    )


def check_icloud_placeholders() -> list[Path]:
    print("\n=== 1. iCloud placeholder 檢查 ===")
    # *.icloud 是 iCloud 還沒下載到本機的檔案佔位符
    out = run(["find", ".", "-name", "*.icloud", "-not", "-path", "./.git/*"], capture=True)
    files = [Path(p) for p in out.stdout.strip().splitlines() if p.strip()]
    if files:
        print(f"  [stop] 偵測到 {len(files)} 個 iCloud placeholder：")
        for f in files[:10]:
            print(f"    {f}")
        if len(files) > 10:
            print(f"    ...（還有 {len(files)-10} 個）")
        print("  請在 Finder 雙擊這些檔案觸發下載，或用 brctl download，完成後再跑本 skill")
    else:
        print("  無 placeholder")
    return files


def collect_changes() -> dict:
    print("\n=== 2. 收集變動 ===")
    out = run(["git", "status", "--porcelain"], capture=True)
    if out.returncode != 0:
        return {"error": out.stderr}
    by_src = {
        "uro_gov_taipei_cases": {"add": 0, "mod": 0, "del": 0},
        "uro_gis_taipei_plans": {"add": 0, "mod": 0, "del": 0},
        "uro_clcoordinate_handouts": {"add": 0, "mod": 0, "del": 0},
        "other": {"add": 0, "mod": 0, "del": 0},
    }
    total = 0
    for line in out.stdout.splitlines():
        if not line.strip():
            continue
        total += 1
        status, _, path = line[:2], line[2], line[3:]
        bucket = "other"
        for src in by_src:
            if path.startswith(f"sources/{src}"):
                bucket = src
                break
        if "?" in status or "A" in status:
            by_src[bucket]["add"] += 1
        elif "D" in status:
            by_src[bucket]["del"] += 1
        else:
            by_src[bucket]["mod"] += 1

    if total == 0:
        print("  無變動可推")
    else:
        print(f"  總變動 {total} 個檔案：")
        for src, counts in by_src.items():
            if any(counts.values()):
                print(f"    {src:35s} 新增 {counts['add']} / 修改 {counts['mod']} / 刪除 {counts['del']}")
    return {"total": total, "by_src": by_src}


def check_large_files() -> list[tuple[Path, int]]:
    print("\n=== 3. 大檔安全網（>99MB，排除 .git 與計畫書）===")
    # 找 99MB 以上、非 .git、非 .icloud 的檔
    out = run(
        ["find", ".", "-type", "f", "-size", "+99M",
         "-not", "-path", "./.git/*", "-not", "-name", "*.icloud"],
        capture=True
    )
    unexpected = []
    for p in out.stdout.strip().splitlines():
        if not p.strip():
            continue
        path = Path(p)
        if PLAN_BOOK_MARKER in path.name:
            continue  # 計畫書應被 .gitignore 排除，跳過
        try:
            size_mb = path.stat().st_size / (1024 * 1024)
        except FileNotFoundError:
            continue
        unexpected.append((path, size_mb))
    if unexpected:
        print(f"  [stop] 偵測到 {len(unexpected)} 個意外的大檔（非計畫書）：")
        for p, sz in unexpected:
            print(f"    {sz:6.1f} MB  {p}")
        print("  GitHub 單檔上限 100MB。請手動處理（加進 .gitignore 或移到別處）後再跑本 skill")
    else:
        print("  無意外大檔")
    return unexpected


def commit_and_push(changes: dict, dry_run: bool) -> int:
    print("\n=== 4. commit + push ===")
    if changes["total"] == 0:
        print("  無變動，跳過 commit/push")
        return 0

    today = dt.date.today().isoformat()
    by = changes["by_src"]
    msg_parts = [f"sync: {today}"]
    detail = []
    for src, label in [
        ("uro_gov_taipei_cases", "cases"),
        ("uro_gis_taipei_plans", "plans"),
        ("uro_clcoordinate_handouts", "handouts"),
    ]:
        c = by[src]
        delta = c["add"] + c["mod"]
        if delta or c["del"]:
            detail.append(f"{label}:+{delta}" + (f"/-{c['del']}" if c["del"] else ""))
    if detail:
        msg_parts.append("— " + " ".join(detail))
    msg = " ".join(msg_parts)
    print(f"  commit message: {msg!r}")

    if dry_run:
        print("  [dry-run] 略過 git add / commit / push")
        return 0

    r = run(["git", "add", "-A"])
    if r.returncode != 0:
        print("[error] git add 失敗")
        return 3
    r = run(["git", "commit", "-m", msg])
    if r.returncode != 0:
        print("[error] git commit 失敗")
        return 4
    r = run(["git", "push"])
    if r.returncode != 0:
        print("[error] git push 失敗。**不會 force-push**，請手動處理衝突或重試。")
        return 5
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="只看會發生什麼，不真的 commit/push")
    args = parser.parse_args()

    print(f"KB root: {KB_ROOT}")
    if not KB_ROOT.exists():
        print(f"[error] 找不到知識庫目錄：{KB_ROOT}")
        return 1
    if not (KB_ROOT / ".git").exists():
        print("[stop] 目錄尚未 init git。請先跑 Workflow A：")
        print(f"       python3 {Path(__file__).parent / 'init_repo.py'}")
        return 2

    placeholders = check_icloud_placeholders()
    if placeholders:
        return 2

    changes = collect_changes()
    if "error" in changes:
        print(f"[error] {changes['error']}")
        return 3

    large = check_large_files()
    if large:
        return 2

    rc = commit_and_push(changes, args.dry_run)
    if rc != 0:
        return rc

    if changes["total"] > 0 and not args.dry_run:
        # 印 push 結果
        out = run(["git", "log", "-1", "--oneline"], capture=True)
        print(f"\n========== 完成 ==========")
        print(f"最新 commit: {out.stdout.strip()}")
        print(f"Repo URL: https://github.com/calvin830812-spec/urban-renewal-kb")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
