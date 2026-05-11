#!/usr/bin/env python3
"""
臺北市都市更新處 - 都更案件 4 大入口同步器

來源：https://uro.gov.taipei/Content_List.aspx?n=309894EC959D5A90 (便民服務)
- 核定案 (News.aspx)
- 公開展覽及公辦公聽會 (News.aspx)
- 公辦公聽會發言要點 (cp.aspx — 靜態頁直接列 PDF)
- 自辦公聽會 (News.aspx)

行為：
- News.aspx 類: 抓 list page → 對每個案件抓 detail page → 抓內含 PDF + 存 case JSON
- cp.aspx 類: 直接抓頁面內所有 PDF link
- 重點：「掛件案件」常有時效性，PDF 在公告期間可能下架，所以「看到就立刻下載快照」
- state.json 以 case_id (News) 或 pdf_url hash (cp) 為 key，已記錄者跳過

可用環境變數 URO_CASES_DIR 覆蓋預設 archive 位置。
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from base64 import b64decode
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

DEFAULT_ARCHIVE = "/Users/zhuangyinglin/Library/Mobile Documents/com~apple~CloudDocs/都更知識庫/sources/uro_gov_taipei_cases"
ROOT = Path(os.environ.get("URO_CASES_DIR", DEFAULT_ARCHIVE)).expanduser().resolve()

STATE_FILE = ROOT / "state.json"
INDEX_CSV = ROOT / "index.csv"
INDEX_MD = ROOT / "index.md"

BASE = "https://uro.gov.taipei"

CATEGORIES = [
    {"key": "核定案", "type": "list",
     "url": "News.aspx?n=84B16ECE22E9FD00&sms=CC49E1BF66CBBEB8"},
    {"key": "公開展覽及公辦公聽會", "type": "list",
     "url": "News.aspx?n=C881AFD2F755EAC7&sms=F7803FDCDEB8E254"},
    {"key": "公辦公聽會發言要點", "type": "static",
     "url": "cp.aspx?n=0F5B969BD24D8D60"},
    {"key": "自辦公聽會", "type": "list",
     "url": "News.aspx?n=1E1F7BC7180BF44C&sms=BCF7679E94E7EECC"},
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

_FILENAME_BANNED = re.compile(r'[/\\:*?"<>|\x00-\x1f]')
_ROC_DATE_RE = re.compile(r"民國\s*(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
# Bare ROC year (no 民國 prefix), e.g. "115年2月26日" — restrict year 90-140 (民國 90-140 ≈ 西元 2001-2051)
_BARE_ROC_DATE_RE = re.compile(r"(?<![\d/-])(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_AD_DATE_RE = re.compile(r"(20\d{2})[\-/年]\s*(\d{1,2})[\-/月]\s*(\d{1,2})")


def sanitize_filename(name: str, max_len: int = 120) -> str:
    cleaned = _FILENAME_BANNED.sub("_", name).strip().rstrip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip()
    return cleaned or "untitled"


def extract_date_from_text(text: str) -> str | None:
    """嘗試從文字中找到日期，回傳 YYYY-MM-DD，找不到就 None。

    優先順序：「民國 NNN 年 X 月 X 日」 → 「NNN 年 X 月 X 日」(裸 ROC)
    → 西元 → None。
    """
    m = _ROC_DATE_RE.search(text)
    if m:
        roc_y, mo, da = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{roc_y + 1911}-{mo:02d}-{da:02d}"
    m = _BARE_ROC_DATE_RE.search(text)
    if m:
        roc_y = int(m.group(1))
        if 90 <= roc_y <= 140:  # 排除西元年誤判
            return f"{roc_y + 1911}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = _AD_DATE_RE.search(text)
    if m:
        return f"{int(m.group(1))}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def decode_download_ashx(url: str) -> str | None:
    """Telerik 風格 Download.ashx?u=<base64> 解碼回真實檔名。"""
    parsed = urlparse(url)
    if "Download.ashx" not in parsed.path:
        return None
    qs = parse_qs(parsed.query)
    u = qs.get("u", [None])[0]
    if not u:
        return None
    try:
        padded = u + "=" * (-len(u) % 4)
        return b64decode(padded).decode("utf-8", errors="replace")
    except Exception:
        return None


def fetch(session: requests.Session, url: str) -> str:
    full = url if url.startswith("http") else f"{BASE}/{url.lstrip('/')}"
    last_err = None
    for attempt in range(1, RETRIES + 1):
        try:
            resp = session.get(full, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return resp.text
        except Exception as e:
            last_err = e
            if attempt < RETRIES:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"fetch failed after {RETRIES} attempts: {last_err}")


def parse_list_page(html: str, category_url: str) -> list[dict]:
    """解析 News.aspx 列表頁，回傳 [{item_id, title, detail_url, list_seq}]。"""
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        seq_el = tds[0]
        link_el = tds[1].find("a")
        if not link_el or not link_el.get("href"):
            continue
        href = link_el["href"]
        # 取得 s= 參數
        m = re.search(r"[?&]s=([A-Z0-9]+)", href)
        if not m:
            continue
        item_id = m.group(1)
        title = link_el.get_text(strip=True)
        if not title:
            title = link_el.get("title", "").strip()
        detail_url = urljoin(f"{BASE}/", href)
        rows.append({
            "item_id": item_id,
            "list_seq": seq_el.get_text(strip=True),
            "title": title,
            "detail_url": detail_url,
        })
    return rows


def parse_detail_page(html: str) -> dict:
    """解析 News_Content.aspx 詳情頁，抓 PDF + 內文 + 試圖找日期。"""
    soup = BeautifulSoup(html, "html.parser")
    # 主內文區塊 — 多個候選 selector
    content = (soup.select_one("div.page-content") or
               soup.select_one("div#CCMS_Content") or
               soup.select_one("article") or soup)
    body_text = content.get_text("\n", strip=True) if content else ""
    publish_date = extract_date_from_text(body_text)

    pdfs = []
    seen_urls = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        is_pdf = (
            href.lower().endswith(".pdf") or
            ("Download.ashx" in href and "u=" in href) or
            ("www-ws.gov.taipei" in href and ".pdf" in href.lower())
        )
        if not is_pdf:
            continue
        full = href if href.startswith("http") else urljoin(f"{BASE}/", href)
        if full in seen_urls:
            continue
        seen_urls.add(full)
        label = a.get_text(strip=True) or a.get("title", "").strip()
        decoded = decode_download_ashx(full)
        pdfs.append({
            "label": label,
            "url": full,
            "decoded_path": decoded,
        })
    return {
        "body_text": body_text,
        "publish_date": publish_date,
        "pdfs": pdfs,
    }


def parse_static_page(html: str) -> dict:
    """解析 cp.aspx 靜態頁面。

    優先策略：找 3 欄表格 (日期 / 案名 / PDF)，每列產出
    {date, title, url}；若無表格，退回扁平的「整頁所有 PDF link」。
    """
    soup = BeautifulSoup(html, "html.parser")
    content = (soup.select_one("div.page-content") or
               soup.select_one("div#CCMS_Content") or soup)
    body_text = content.get_text("\n", strip=True) if content else ""
    pdfs = []
    seen_urls = set()

    def is_pdf_href(href: str) -> bool:
        return (
            href.lower().endswith(".pdf") or
            ("Download.ashx" in href and "u=" in href) or
            ("www-ws.gov.taipei" in href and ".pdf" in href.lower())
        )

    # 嘗試表格模式
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        # 驗證 header
        header_tds = rows[0].find_all(["th", "td"])
        header_text = " ".join(td.get_text(strip=True) for td in header_tds)
        if not (("日期" in header_text or "公聽會" in header_text)
                and ("案名" in header_text or "案件" in header_text)):
            continue
        # 跳過 header 列
        for tr in rows[1:]:
            tds = tr.find_all("td")
            if len(tds) < 3:
                continue
            date_text = tds[0].get_text(strip=True)
            title = tds[1].get_text(strip=True)
            link = tds[2].find("a", href=True)
            if not link:
                continue
            href = link["href"].strip()
            if not is_pdf_href(href):
                continue
            full = href if href.startswith("http") else urljoin(f"{BASE}/", href)
            if full in seen_urls:
                continue
            seen_urls.add(full)
            pdfs.append({
                "label": title,
                "url": full,
                "decoded_path": decode_download_ashx(full),
                "publish_date": extract_date_from_text(date_text),
                "raw_date": date_text,
            })
        if pdfs:
            return {"body_text": body_text, "pdfs": pdfs}

    # 退路：扁平模式
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not is_pdf_href(href):
            continue
        full = href if href.startswith("http") else urljoin(f"{BASE}/", href)
        if full in seen_urls:
            continue
        seen_urls.add(full)
        label = a.get_text(strip=True) or a.get("title", "").strip()
        pdfs.append({
            "label": label,
            "url": full,
            "decoded_path": decode_download_ashx(full),
            "publish_date": None,
            "raw_date": None,
        })
    return {"body_text": body_text, "pdfs": pdfs}


def download_pdf(session: requests.Session, url: str, dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    last_err = None
    for attempt in range(1, RETRIES + 1):
        try:
            with session.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True) as resp:
                resp.raise_for_status()
                ct = resp.headers.get("Content-Type", "").lower()
                size = 0
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                            size += len(chunk)
                # sanity: 至少 PDF magic header
                with open(tmp, "rb") as f:
                    head = f.read(4)
                if head != b"%PDF":
                    raise RuntimeError(
                        f"not a PDF (Content-Type={ct}, head={head!r}, size={size})"
                    )
                tmp.replace(dest)
                return size
        except Exception as e:
            last_err = e
            if attempt < RETRIES:
                time.sleep(2 ** attempt)
    if tmp.exists():
        tmp.unlink()
    raise RuntimeError(f"download failed after {RETRIES} attempts: {last_err}")


def url_hash(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {"cases": {}, "static_pdfs": {}}
    return {"cases": {}, "static_pdfs": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def sync_list_category(session, cat: dict, state: dict) -> dict:
    """同步一個 News.aspx 類別 (僅更新 state，不直接寫 index)。"""
    print(f"\n=== {cat['key']} (list) ===")
    cat_dir = ROOT / cat["key"]
    pdfs_dir = cat_dir / "pdfs"
    cases_dir = cat_dir / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    pdfs_dir.mkdir(parents=True, exist_ok=True)

    list_html = fetch(session, cat["url"])
    items = parse_list_page(list_html, cat["url"])
    print(f"  列表共 {len(items)} 筆案件")

    new = skipped = failed = pdf_new = 0
    for idx, item in enumerate(items, 1):
        item_id = item["item_id"]
        title = item["title"]
        case_key = f"{cat['key']}::{item_id}"
        if case_key in state["cases"] and state["cases"][case_key].get("local_metadata_path"):
            print(f"  [{idx}/{len(items)}] [skip] {title[:40]}")
            skipped += 1
            continue
        try:
            print(f"  [{idx}/{len(items)}] [get ] {title[:40]}")
            detail_html = fetch(session, item["detail_url"])
            detail = parse_detail_page(detail_html)
            case_meta = {
                "category": cat["key"],
                "item_id": item_id,
                "title": title,
                "list_seq": item["list_seq"],
                "detail_url": item["detail_url"],
                "publish_date": detail["publish_date"],
                "body_text": detail["body_text"],
                "pdfs_meta": detail["pdfs"],
                "first_seen": dt.datetime.now().isoformat(timespec="seconds"),
            }
            metadata_path = cases_dir / f"{item_id}.json"
            metadata_path.write_text(
                json.dumps(case_meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            local_pdfs = []
            date_prefix = detail["publish_date"] or dt.date.today().isoformat()
            short_title = sanitize_filename(title, max_len=80)
            for pi, pdf in enumerate(detail["pdfs"], 1):
                suffix = f"_{pi}" if len(detail["pdfs"]) > 1 else ""
                fname = f"{date_prefix}_{short_title}_{item_id[:8]}{suffix}.pdf"
                local = pdfs_dir / fname
                try:
                    size = download_pdf(session, pdf["url"], local)
                    local_pdfs.append({
                        "label": pdf["label"],
                        "url": pdf["url"],
                        "local_path": str(local.relative_to(ROOT)),
                        "size_bytes": size,
                    })
                    pdf_new += 1
                except Exception as pe:
                    print(f"      [pdf-FAIL] {pdf['url'][:60]}: {pe}", file=sys.stderr)
                    failed += 1
            state["cases"][case_key] = {
                "category": cat["key"],
                "item_id": item_id,
                "title": title,
                "publish_date": detail["publish_date"],
                "detail_url": item["detail_url"],
                "local_metadata_path": str(metadata_path.relative_to(ROOT)),
                "local_pdfs": local_pdfs,
                "first_seen": case_meta["first_seen"],
            }
            new += 1
        except Exception as e:
            print(f"  [FAIL] {title[:40]}: {e}", file=sys.stderr)
            failed += 1
    print(f"  小計: 新案 {new} / 跳過 {skipped} / 失敗 {failed} / PDF 新增 {pdf_new}")
    return {"new": new, "skipped": skipped, "failed": failed, "pdf_new": pdf_new}


def build_rows_from_state(state: dict) -> list:
    """從 state.json 建構統一 rows for index — 包含所有歷史案件，不限本輪新增。"""
    rows = []
    for case_key, c in state.get("cases", {}).items():
        local_pdfs = c.get("local_pdfs") or []
        if local_pdfs:
            for lp in local_pdfs:
                rows.append({
                    "category": c["category"],
                    "item_id": c["item_id"],
                    "publish_date": c.get("publish_date") or "",
                    "title": c["title"],
                    "pdf_label": lp.get("label") or "",
                    "local_path": lp.get("local_path") or "",
                    "source_url": lp.get("url") or "",
                    "detail_url": c.get("detail_url") or "",
                })
        else:
            rows.append({
                "category": c["category"],
                "item_id": c["item_id"],
                "publish_date": c.get("publish_date") or "",
                "title": c["title"],
                "pdf_label": "(無附件)",
                "local_path": "",
                "source_url": "",
                "detail_url": c.get("detail_url") or "",
            })
    cat_url_map = {c["key"]: f"{BASE}/{c['url']}" for c in CATEGORIES}
    for key, s in state.get("static_pdfs", {}).items():
        rows.append({
            "category": s["category"],
            "item_id": "",
            "publish_date": s.get("publish_date") or "",
            "title": s.get("label") or "(靜態 PDF)",
            "pdf_label": s.get("label") or "",
            "local_path": s.get("local_path") or "",
            "source_url": s.get("url") or "",
            "detail_url": cat_url_map.get(s["category"], ""),
        })
    return rows


def sync_static_category(session, cat: dict, state: dict) -> dict:
    """同步一個 cp.aspx 靜態頁類別 (僅更新 state，不直接寫 index)。"""
    print(f"\n=== {cat['key']} (static) ===")
    cat_dir = ROOT / cat["key"]
    pdfs_dir = cat_dir / "pdfs"
    pdfs_dir.mkdir(parents=True, exist_ok=True)

    html = fetch(session, cat["url"])
    parsed = parse_static_page(html)
    print(f"  頁面共 {len(parsed['pdfs'])} 個 PDF 連結")

    new = skipped = failed = 0
    for pi, pdf in enumerate(parsed["pdfs"], 1):
        key = f"{cat['key']}::{url_hash(pdf['url'])}"
        if key in state["static_pdfs"] and Path(ROOT / state["static_pdfs"][key]["local_path"]).exists():
            skipped += 1
            continue
        # 命名: {date}_{title-clean}_{hash6}.pdf
        date_prefix = pdf.get("publish_date") or "0000-00-00"
        label_clean = sanitize_filename(pdf["label"] or f"item{pi}", max_len=80)
        fname = f"{date_prefix}_{label_clean}_{url_hash(pdf['url'])}.pdf"
        local = pdfs_dir / fname
        try:
            print(f"  [{pi}/{len(parsed['pdfs'])}] [get ] {label_clean[:50]}")
            size = download_pdf(session, pdf["url"], local)
            state["static_pdfs"][key] = {
                "category": cat["key"],
                "label": pdf["label"],
                "url": pdf["url"],
                "publish_date": pdf.get("publish_date"),
                "raw_date": pdf.get("raw_date"),
                "local_path": str(local.relative_to(ROOT)),
                "size_bytes": size,
                "downloaded_at": dt.datetime.now().isoformat(timespec="seconds"),
            }
            new += 1
        except Exception as e:
            print(f"  [FAIL] {(pdf['label'] or '(unknown)')[:50]}: {e}", file=sys.stderr)
            failed += 1
    print(f"  小計: 新增 {new} / 跳過 {skipped} / 失敗 {failed}")
    return {"new": new, "skipped": skipped, "failed": failed, "pdf_new": new}


def write_index_csv(rows: list) -> None:
    with INDEX_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["類別", "案件序號", "公告日期", "案件名稱", "文件標籤",
                    "PDF 本地路徑", "PDF 來源連結", "詳情頁連結"])
        for r in sorted(rows, key=lambda x: (x["category"], x["publish_date"] or "0000-00-00", x["title"]), reverse=False):
            w.writerow([
                r["category"], r["item_id"], r["publish_date"], r["title"],
                r["pdf_label"] or "", r["local_path"], r["source_url"], r["detail_url"],
            ])


def _md_escape(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ")


def write_index_md(rows: list) -> None:
    today = dt.date.today().isoformat()
    by_cat = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r)
    lines = [
        "# 臺北市都市更新處 — 都更案件索引",
        "",
        f"來源：[便民服務]({BASE}/Content_List.aspx?n=309894EC959D5A90)",
        f"最後更新：{today}",
        f"共 {len(rows)} 筆 PDF / 案件項目",
        "",
    ]
    for cat in [c["key"] for c in CATEGORIES]:
        items = by_cat.get(cat, [])
        if not items:
            continue
        lines += [
            f"## {cat} ({len(items)} 項)",
            "",
            "| 公告日期 | 案件名稱 | PDF |",
            "| --- | --- | --- |",
        ]
        for r in sorted(items, key=lambda x: x["publish_date"] or "0000-00-00", reverse=True):
            pdf_cell = f"[📄]({r['local_path']})" if r["local_path"] else "—"
            lines.append(
                f"| {r['publish_date'] or '—'} | "
                f"[{_md_escape(r['title'][:80])}]({_md_escape(r['detail_url'])}) | "
                f"{pdf_cell} |"
            )
        lines.append("")
    INDEX_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    print(f"Archive: {ROOT}")
    ROOT.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    state = load_state()
    state.setdefault("cases", {})
    state.setdefault("static_pdfs", {})
    summary = {"new": 0, "skipped": 0, "failed": 0, "pdf_new": 0}

    for cat in CATEGORIES:
        if cat["type"] == "list":
            s = sync_list_category(session, cat, state)
        else:
            s = sync_static_category(session, cat, state)
        for k in summary:
            summary[k] += s.get(k, 0)

    save_state(state)

    rows = build_rows_from_state(state)
    write_index_csv(rows)
    write_index_md(rows)

    print("\n========== 總結 ==========")
    print(f"新增案件: {summary['new']}")
    print(f"跳過: {summary['skipped']}")
    print(f"新下載 PDF: {summary['pdf_new']}")
    print(f"失敗: {summary['failed']}")
    print(f"index 共 {len(rows)} 筆")
    print(f"index.csv: {INDEX_CSV}")
    print(f"index.md: {INDEX_MD}")
    return 0 if summary["failed"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
