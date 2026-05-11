#!/usr/bin/env python3
"""
都更知識庫 — 跨來源 master index 產生器

讀取 sources/*/index.csv 並合併成統一的 master_index.csv 與 master_index.md。
讓使用者能用單一檔查所有來源的 PDF。

使用：
    python3 tools/build_master_index.py
"""
from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = ROOT / "sources"
MASTER_CSV = ROOT / "master_index.csv"
MASTER_MD = ROOT / "master_index.md"

# 各來源的 index.csv schema 不同，所以這裡定義 mapping
SOURCE_PROFILES = {
    "uro_clcoordinate_handouts": {
        "display_name": "臺北市都更教育訓練講義",
        "doc_type": "教育訓練講義",
        "src_url": "http://uro.clcoordinate.com/pgDownload.aspx",
        "row_to_master": lambda row, source_dir: {
            "source_id": "uro_clcoordinate_handouts",
            "source_name": "臺北市都更教育訓練講義",
            "doc_type": "教育訓練講義",
            "subcategory": row.get("分類", ""),
            "publish_date": row.get("日期", ""),
            "title": row.get("課程名稱", ""),
            "local_path": str(source_dir / row["PDF 本地路徑"]) if row.get("PDF 本地路徑") else "",
            "source_url": row.get("PDF 來源連結", ""),
            "extra_url": row.get("YouTube 連結", ""),
        },
    },
    "uro_gov_taipei_cases": {
        "display_name": "臺北市都更處 — 都更案掛件",
        "doc_type": "都更案掛件",
        "src_url": "https://uro.gov.taipei/Content_List.aspx?n=309894EC959D5A90",
        "row_to_master": lambda row, source_dir: {
            "source_id": "uro_gov_taipei_cases",
            "source_name": "臺北市都更處 — 都更案掛件",
            "doc_type": "都更案掛件",
            "subcategory": row.get("類別", ""),
            "publish_date": row.get("公告日期", ""),
            "title": row.get("案件名稱", ""),
            "local_path": str(source_dir / row["PDF 本地路徑"]) if row.get("PDF 本地路徑") else "",
            "source_url": row.get("PDF 來源連結", ""),
            "extra_url": row.get("詳情頁連結", ""),
        },
    },
}


def load_source_rows(source_id: str, source_dir: Path) -> list[dict]:
    """讀某個 source 的 index.csv 並轉為 master schema。"""
    profile = SOURCE_PROFILES.get(source_id)
    if not profile:
        print(f"  [warn] 未知 source: {source_id}, 跳過")
        return []
    csv_path = source_dir / "index.csv"
    if not csv_path.exists():
        print(f"  [warn] {source_id}: index.csv 不存在 (可能還沒 sync 過)")
        return []
    rows = []
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(profile["row_to_master"](r, source_dir))
    return rows


def write_master_csv(rows: list[dict]) -> None:
    cols = ["source_id", "source_name", "doc_type", "subcategory",
            "publish_date", "title", "local_path", "source_url", "extra_url"]
    with MASTER_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in sorted(rows, key=lambda x: (x["source_id"], x["subcategory"],
                                             x["publish_date"] or "0000-00-00",
                                             x["title"]),
                        reverse=False):
            w.writerow({k: r.get(k, "") for k in cols})


def write_master_md(rows: list[dict]) -> None:
    today = dt.date.today().isoformat()
    by_source = {}
    for r in rows:
        by_source.setdefault(r["source_id"], []).append(r)

    lines = [
        "# 都更知識庫 — Master Index",
        "",
        f"最後更新：{today}",
        f"共 {len(rows)} 筆資料、{len(by_source)} 個資料來源",
        "",
        "## 統計",
        "",
        "| 來源 | 類型 | 文件數 |",
        "| --- | --- | --- |",
    ]
    for source_id, src_rows in sorted(by_source.items()):
        profile = SOURCE_PROFILES.get(source_id, {})
        lines.append(
            f"| {profile.get('display_name', source_id)} | {profile.get('doc_type', '?')} | {len(src_rows)} |"
        )
    lines += ["", "## 各來源詳細", ""]

    for source_id, src_rows in sorted(by_source.items()):
        profile = SOURCE_PROFILES.get(source_id, {})
        display = profile.get("display_name", source_id)
        src_url = profile.get("src_url", "")
        lines += [
            f"### {display}",
            "",
            f"來源網站：[{src_url}]({src_url})  ",
            f"資料筆數：{len(src_rows)}",
            "",
        ]
        # 子類別細分
        by_sub = {}
        for r in src_rows:
            by_sub.setdefault(r["subcategory"] or "(無分類)", []).append(r)
        for sub, items in sorted(by_sub.items()):
            lines += [
                f"#### {sub} ({len(items)})",
                "",
                "| 公告日期 | 標題 | PDF |",
                "| --- | --- | --- |",
            ]
            for r in sorted(items, key=lambda x: x["publish_date"] or "0000-00-00", reverse=True):
                title = (r["title"] or "")[:80].replace("|", "\\|")
                pdf_cell = f"[📄]({r['local_path']})" if r["local_path"] else "—"
                lines.append(
                    f"| {r['publish_date'] or '—'} | {title} | {pdf_cell} |"
                )
            lines.append("")
    MASTER_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    print(f"Knowledge base root: {ROOT}")
    if not SOURCES_DIR.exists():
        print(f"找不到 sources/ 目錄：{SOURCES_DIR}")
        return 1
    all_rows = []
    sources = sorted(d for d in SOURCES_DIR.iterdir() if d.is_dir())
    print(f"發現 {len(sources)} 個來源：")
    for sd in sources:
        print(f"  - {sd.name}")
        rows = load_source_rows(sd.name, sd)
        print(f"    讀入 {len(rows)} 筆")
        all_rows.extend(rows)
    write_master_csv(all_rows)
    write_master_md(all_rows)
    print(f"\n總計：{len(all_rows)} 筆")
    print(f"  → {MASTER_CSV}")
    print(f"  → {MASTER_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
