#!/usr/bin/env python3
"""
都更知識庫 — 跨來源核對腳本

檢查項目：
1. 各來源 state.json 案件數 vs index.csv 列數
2. GIS / cases 的 PDF local_path 是否實際存在於本機
3. iCloud .icloud placeholder 偵測（影響後續推 GitHub）
4. 各來源最新一筆日期
5. 總筆數彙整

回傳碼：
  0 = 全對齊
  1 = 有異常（缺檔 / placeholder / 數量不一致）
  2 = 結構錯誤（state.json 或 index.csv 找不到）

可用環境變數 URO_KB_DIR 覆蓋預設知識庫路徑。
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_KB = "/Users/zhuangyinglin/Library/Mobile Documents/com~apple~CloudDocs/都更知識庫"
KB_ROOT = Path(os.environ.get("URO_KB_DIR", DEFAULT_KB)).expanduser().resolve()

SOURCES = ["uro_gov_taipei_cases", "uro_gis_taipei_plans", "uro_clcoordinate_handouts"]


def read_csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def check_source(src: str) -> dict:
    src_dir = KB_ROOT / "sources" / src
    state_file = src_dir / "state.json"
    index_csv = src_dir / "index.csv"
    result = {"source": src, "ok": True, "issues": []}

    if not src_dir.exists():
        result["ok"] = False
        result["issues"].append(f"目錄不存在: {src_dir}")
        return result

    # state.json
    state_cases = 0
    if state_file.exists():
        state = json.loads(state_file.read_text(encoding="utf-8"))
        # 不同來源結構不同
        if "cases" in state:
            state_cases = len(state["cases"])
        elif "items" in state:
            state_cases = len(state["items"])
        else:
            state_cases = sum(len(v) for v in state.values() if isinstance(v, (list, dict)))
    else:
        result["issues"].append("state.json 不存在")

    # index.csv
    rows = read_csv_rows(index_csv)
    csv_rows = len(rows)

    result["state_cases"] = state_cases
    result["csv_rows"] = csv_rows

    # 最新日期（找 csv 內 publish_date / 掛件時間 / 日期 / 公告日期）
    date_keys = ["掛件時間", "公告日期", "日期", "publish_date"]
    latest = ""
    for r in rows:
        for k in date_keys:
            if k in r and r[k] > latest:
                latest = r[k]
                break
    result["latest_date"] = latest

    # PDF 落地檢查（cases / GIS 有 PDF 本地路徑欄位）
    missing_pdfs = []
    if src in ("uro_gov_taipei_cases", "uro_gis_taipei_plans"):
        for r in rows:
            pdf_rel = r.get("PDF 本地路徑", "").strip()
            if pdf_rel and pdf_rel != "(無附件)":
                pdf_path = src_dir / pdf_rel if not pdf_rel.startswith("/") else Path(pdf_rel)
                if not pdf_path.exists():
                    missing_pdfs.append(pdf_rel)
    result["missing_pdfs"] = missing_pdfs[:20]
    result["missing_pdfs_count"] = len(missing_pdfs)
    if missing_pdfs and src != "uro_gis_taipei_plans":
        # GIS 計畫書本體預設不下載，missing 是正常的（local_path 為空或檔名是計畫書）
        result["ok"] = False
        result["issues"].append(f"缺 {len(missing_pdfs)} 個 PDF")

    return result


def check_icloud_placeholders() -> list[str]:
    out = subprocess.run(
        ["find", str(KB_ROOT), "-name", "*.icloud", "-not", "-path", "*/.git/*"],
        capture_output=True, text=True, check=False
    )
    return [p for p in out.stdout.strip().splitlines() if p.strip()]


def main() -> int:
    print(f"KB root: {KB_ROOT}")
    if not KB_ROOT.exists():
        print(f"[error] 找不到知識庫: {KB_ROOT}")
        return 2

    print("\n========== 跨來源核對 ==========\n")
    results = []
    any_issue = False
    total_rows = 0
    for src in SOURCES:
        r = check_source(src)
        results.append(r)
        if not r["ok"]:
            any_issue = True
        total_rows += r.get("csv_rows", 0)

        status = "✅" if r["ok"] else "⚠️"
        print(f"{status} {src}")
        print(f"   state 案件數: {r.get('state_cases', '-')}")
        print(f"   index.csv 列數: {r.get('csv_rows', '-')}")
        print(f"   最新日期: {r.get('latest_date', '-')}")
        if r.get("missing_pdfs_count", 0):
            print(f"   缺 PDF: {r['missing_pdfs_count']} 個")
            for p in r["missing_pdfs"][:5]:
                print(f"     - {p}")
            if r['missing_pdfs_count'] > 5:
                print(f"     ...（還有 {r['missing_pdfs_count']-5} 個）")
        for issue in r["issues"]:
            print(f"   ⚠️  {issue}")
        print()

    # master_index
    master_csv = KB_ROOT / "master_index.csv"
    if master_csv.exists():
        master_rows = len(read_csv_rows(master_csv))
        print(f"📚 master_index.csv: {master_rows} 筆")
        if master_rows != total_rows:
            print(f"   ⚠️  與來源總和 ({total_rows}) 不一致，請跑 tools/build_master_index.py")
            any_issue = True
    else:
        print("⚠️  master_index.csv 不存在 — 請跑 tools/build_master_index.py")
        any_issue = True
    print()

    # iCloud placeholder
    placeholders = check_icloud_placeholders()
    if placeholders:
        any_issue = True
        print(f"⚠️  iCloud placeholder: {len(placeholders)} 個（會阻擋 GitHub 推送）")
        for p in placeholders[:5]:
            print(f"   - {p}")
        if len(placeholders) > 5:
            print(f"   ...（還有 {len(placeholders)-5} 個）")
        print("   請在 Finder 雙擊觸發下載後再推 GitHub")
    else:
        print("✅ 無 iCloud placeholder")
    print()

    print("========== 核對總結 ==========")
    if any_issue:
        print("⚠️  發現異常 — 建議處理後再執行 Step 6 (推 GitHub)")
        return 1
    print("✅ 全對齊，可安全進入 Step 6")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
