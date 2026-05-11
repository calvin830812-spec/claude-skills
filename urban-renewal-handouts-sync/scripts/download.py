#!/usr/bin/env python3
"""
臺北市都市再生教育訓練 - 下載專區 PDF 自動下載器（skill 版）

來源：http://uro.clcoordinate.com/pgDownload.aspx

預設 archive 路徑：
    /Users/zhuangyinglin/Documents/Claude/Projects/抓網站上的都更檔案下載/

可用環境變數 URO_ARCHIVE_DIR 覆蓋（給其他機器或測試使用）：
    URO_ARCHIVE_DIR=/path/to/archive python3 download.py

行為：
- 抓全部課程 PDF，存到 <archive>/pdfs/
- 檔名改為 {日期}_{課程名稱}.pdf
- 產出 index.csv（utf-8-sig，給 Excel）與 index.md（含可點擊連結）
- 用 state.json 做增量判斷，重跑只抓新檔
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

DEFAULT_ARCHIVE = "/Users/zhuangyinglin/Library/Mobile Documents/com~apple~CloudDocs/都更知識庫/sources/uro_clcoordinate_handouts"
ROOT = Path(os.environ.get("URO_ARCHIVE_DIR", DEFAULT_ARCHIVE)).expanduser().resolve()

PDF_DIR = ROOT / "pdfs"
STATE_FILE = ROOT / "state.json"
INDEX_CSV = ROOT / "index.csv"
INDEX_MD = ROOT / "index.md"

PAGE_URL = "http://uro.clcoordinate.com/pgDownload.aspx"
CATEGORIES = [
    ("620", "專業者"),
    ("621", "一般民眾"),
    ("622", "大專院校"),
    ("623", "自主更新"),
]
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}
TIMEOUT = 30
RETRIES = 3


def fetch_all_page(session):
    resp = session.get(PAGE_URL, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    def grab(name):
        el = soup.find("input", attrs={"name": name})
        return el.get("value", "") if el else ""

    viewstate = {
        "__VIEWSTATE": grab("__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": grab("__VIEWSTATEGENERATOR"),
        "__EVENTVALIDATION": grab("__EVENTVALIDATION"),
    }
    return resp.text, viewstate


def parse_rows(html):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("tr.rgRow, tr.rgAltRow"):
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        date = tds[0].get_text(strip=True)
        name = tds[1].get_text(strip=True)
        pdf_a = tds[2].find("a")
        pdf_url = (pdf_a.get("href") or "").strip() if pdf_a else ""
        video_a = tds[3].find("a")
        video_url = ""
        if video_a:
            classes = video_a.get("class") or []
            href = (video_a.get("href") or "").strip()
            if href and "hidden" not in classes:
                video_url = href
        if not pdf_url:
            continue
        rows.append({
            "date": date,
            "name": name,
            "pdf_url": pdf_url,
            "video_url": video_url,
        })
    return rows


def fetch_category(session, viewstate, value, text):
    client_state = json.dumps({
        "logEntries": [],
        "value": value,
        "text": text,
        "enabled": True,
        "checkedIndices": [],
        "checkedItemsTextOverflows": False,
    }, ensure_ascii=False)
    data = {
        "__EVENTTARGET": "ctl00$ContentPlaceHolder1$combCat",
        "__EVENTARGUMENT": "",
        "__VIEWSTATE": viewstate["__VIEWSTATE"],
        "__VIEWSTATEGENERATOR": viewstate["__VIEWSTATEGENERATOR"],
        "__EVENTVALIDATION": viewstate["__EVENTVALIDATION"],
        "ctl00$ContentPlaceHolder1$combCat": text,
        "ctl00$ContentPlaceHolder1$combCat_ClientState": client_state,
    }
    resp = session.post(PAGE_URL, data=data, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return {r["pdf_url"] for r in parse_rows(resp.text)}


def build_category_map(session, viewstate, all_urls):
    mapping = {u: [] for u in all_urls}
    for value, text in CATEGORIES:
        try:
            urls = fetch_category(session, viewstate, value, text)
            print(f"  分類 {text}({value}): {len(urls)} 筆")
            for u in urls:
                if u in mapping:
                    mapping[u].append(text)
        except Exception as e:
            print(f"  分類 {text}({value}) 失敗：{e}", file=sys.stderr)
    result = {}
    for u, cats in mapping.items():
        if len(cats) == len(CATEGORIES):
            result[u] = "全部"
        elif not cats:
            result[u] = "未分類"
        else:
            result[u] = "、".join(cats)
    return result


_FILENAME_BANNED = re.compile(r'[/\\:*?"<>|\x00-\x1f]')


def sanitize_filename(name):
    cleaned = _FILENAME_BANNED.sub("_", name).strip().rstrip(".")
    if len(cleaned) > 200:
        cleaned = cleaned[:200].rstrip()
    return cleaned or "untitled"


def download_pdf(session, url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    last_err = None
    for attempt in range(1, RETRIES + 1):
        try:
            with session.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True) as resp:
                resp.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
            tmp.replace(dest)
            return
        except Exception as e:
            last_err = e
            if attempt < RETRIES:
                time.sleep(2 ** attempt)
    if tmp.exists():
        tmp.unlink()
    raise RuntimeError(f"download failed after {RETRIES} attempts: {last_err}")


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_index_csv(rows):
    with INDEX_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["日期", "課程名稱", "分類", "PDF 本地路徑", "PDF 來源連結", "YouTube 連結"])
        for r in sorted(rows, key=lambda x: (x["date"], x["name"]), reverse=True):
            w.writerow([
                r["date"],
                r["name"],
                r["category"],
                r["local_path"],
                r["pdf_url"],
                r["video_url"],
            ])


def _md_escape(s):
    return s.replace("|", "\\|")


def write_index_md(rows):
    today = dt.date.today().isoformat()
    lines = [
        "# 臺北市都市再生教育訓練 — 講義索引",
        "",
        f"來源：[下載專區]({PAGE_URL})",
        f"最後更新：{today}",
        f"共 {len(rows)} 筆",
        "",
        "| 日期 | 課程名稱 | 分類 | PDF | 影音 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in sorted(rows, key=lambda x: (x["date"], x["name"]), reverse=True):
        pdf_cell = f"[📄]({r['local_path']})" if r["local_path"] else "—"
        video_cell = f"[▶]({r['video_url']})" if r["video_url"] else "—"
        lines.append(
            f"| {r['date']} | {_md_escape(r['name'])} | {_md_escape(r['category'])} | {pdf_cell} | {video_cell} |"
        )
    INDEX_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    print(f"Archive: {ROOT}")
    ROOT.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    print("[1/4] 抓取主頁(--All--)...")
    html, viewstate = fetch_all_page(session)
    rows = parse_rows(html)
    if not rows:
        print("錯誤：找不到任何課程資料，請檢查網站結構是否變更", file=sys.stderr)
        return 1
    print(f"  共 {len(rows)} 筆課程")

    print("[2/4] 抓取各分類標籤...")
    cat_map = build_category_map(session, viewstate, {r["pdf_url"] for r in rows})

    print("[3/4] 下載 PDF...")
    state = load_state()
    new = skipped = failed = 0
    for r in rows:
        r["category"] = cat_map.get(r["pdf_url"], "未分類")
        filename = f'{r["date"]}_{sanitize_filename(r["name"])}.pdf'
        local = PDF_DIR / filename
        r["local_path"] = str(local.relative_to(ROOT))

        if r["pdf_url"] in state and local.exists():
            print(f"  [skip] {filename}")
            skipped += 1
            continue
        try:
            print(f"  [get ] {filename}")
            download_pdf(session, r["pdf_url"], local)
            state[r["pdf_url"]] = {
                "filename": filename,
                "downloaded_at": dt.datetime.now().isoformat(timespec="seconds"),
            }
            new += 1
        except Exception as e:
            print(f"  [FAIL] {filename}: {e}", file=sys.stderr)
            failed += 1

    save_state(state)

    print("[4/4] 寫入索引...")
    write_index_csv(rows)
    write_index_md(rows)
    print(f"  → {INDEX_CSV.name}")
    print(f"  → {INDEX_MD.name}")

    print(f"\n總結：新增 {new} / 跳過 {skipped} / 失敗 {failed}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
