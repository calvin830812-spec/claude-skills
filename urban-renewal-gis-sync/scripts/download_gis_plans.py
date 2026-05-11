#!/usr/bin/env python3
"""
臺北市都更雲端 GIS — 公告公文 / 公開計畫書 同步器

來源：https://gis.uro.taipei
- ashx/Get_updcase_list.ashx       — 用 (段, 母號, 子號) 找案件
- ashx/get_project168_top.ashx     — 案件 header (案名/實施者/位置/各階段日期)
- ashx/Get_project168_eighth.ashx  — 公告公文 PDF 清單 (OD_DOCPATH 等)
- ashx/Get_project168_ten.ashx     — 公開計畫書 PDF 清單 (公展期內才有)
- ashx/DownloadODFile.ashx         — 下載 PDF 本體

行為：
- 從 sources/uro_gov_taipei_cases/index.csv 抽 (行政區, 段, 母號, 子號) 為種子
- 對每個種子查 GIS 案件清單 → 過濾出 r_progress_detail 內部 case_id
- 對每個內部 case_id 抓 top + eighth + ten，下載新 PDF
- state.json 記錄已下載過的案件與 PDF，增量同步

可用環境變數 URO_GIS_DIR 覆蓋預設 archive 位置。
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs, quote

import requests

DEFAULT_ARCHIVE = "/Users/zhuangyinglin/Library/Mobile Documents/com~apple~CloudDocs/都更知識庫/sources/uro_gis_taipei_plans"
SEED_ARCHIVE = "/Users/zhuangyinglin/Library/Mobile Documents/com~apple~CloudDocs/都更知識庫/sources/uro_gov_taipei_cases"

ROOT = Path(os.environ.get("URO_GIS_DIR", DEFAULT_ARCHIVE)).expanduser().resolve()
SEED_ROOT = Path(SEED_ARCHIVE)

# 公開計畫書本體單檔常 100MB-500MB，預設只記 metadata 不下載；
# 設 URO_GIS_DOWNLOAD_PLAN_BOOKS=1 才會實際下載 ten PDF。
DOWNLOAD_PLAN_BOOKS = os.environ.get("URO_GIS_DOWNLOAD_PLAN_BOOKS", "") == "1"

# 設 URO_GIS_FULL_SWEEP=1：除了從 uro_gov_taipei_cases 抽種子之外，
# 也對 12 行政區整批做 GetUpdQuery 列舉所有自行劃定核准單元，
# 把案名解析出 (段, 母號) 補入種子集，覆蓋全市更新單元。
FULL_SWEEP = os.environ.get("URO_GIS_FULL_SWEEP", "") == "1"

# 計畫書本體單檔 100MB-500MB；本機若是 iCloud 路徑，下載速度可能 > iCloud 上傳速度
# 而塞滿磁碟。每抓 N 本計畫書暫停 M 秒讓 iCloud 上傳釋出本機快取。
PLAN_BOOK_BATCH = int(os.environ.get("URO_GIS_PLAN_BATCH", "5"))
PLAN_BOOK_PAUSE = int(os.environ.get("URO_GIS_PLAN_PAUSE", "600"))  # 預設 10 分鐘
MIN_FREE_GB = int(os.environ.get("URO_GIS_MIN_FREE_GB", "5"))

STATE_FILE = ROOT / "state.json"
INDEX_CSV = ROOT / "index.csv"
INDEX_MD = ROOT / "index.md"

BASE = "https://gis.uro.taipei"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
}
TIMEOUT = 30
RETRIES = 3

WARDS = ("松山區", "信義區", "大安區", "中山區", "中正區", "大同區",
         "萬華區", "文山區", "南港區", "內湖區", "士林區", "北投區")
WARDS_RE = "(" + "|".join(WARDS) + ")"

SECT_RE = re.compile(
    rf"{WARDS_RE}([一-龥]{{1,8}}段[一二三四五六七八九十]+小段|"
    rf"[一-龥]{{1,8}}段|"
    rf"[一-龥]{{1,8}}[一二三四五六七八九十]+小段)\s*(\d+)(?:-(\d+))?\s*地號"
)

_FILENAME_BANNED = re.compile(r'[/\\:*?"<>|\x00-\x1f]')


def sanitize_filename(name: str, max_len: int = 100) -> str:
    cleaned = _FILENAME_BANNED.sub("_", name).strip().rstrip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip()
    return cleaned or "untitled"


def post(session: requests.Session, path: str, data: str) -> str:
    url = f"{BASE}/{path.lstrip('/')}"
    last_err = None
    for attempt in range(1, RETRIES + 1):
        try:
            resp = session.post(url, data=data, headers={
                **HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
            }, timeout=TIMEOUT)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return resp.text
        except Exception as e:
            last_err = e
            if attempt < RETRIES:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"POST {path} failed: {last_err}")


def parse_json_lenient(text: str):
    """部分 ashx 回傳含未跳脫的控制字元，先過濾掉再 parse。"""
    if not text or text.strip() in ("", "[]", "err"):
        return []
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return []


def get_upd_query_count(session: requests.Session, ward: str) -> int:
    """GetUpdQuery type=count，回傳該行政區自行劃定核准單元總數。"""
    text = post(session, "ashx/GetUpdQuery.ashx",
                f"type=count&case_ward={quote(ward)}")
    arr = parse_json_lenient(text)
    return arr[0].get("upd_count", 0) if arr else 0


def get_upd_query_page(session: requests.Session, ward: str,
                       page_index: int, page_size: int = 100) -> list[dict]:
    """GetUpdQuery type=query 分頁列舉某行政區的案件。"""
    data = (f"type=query&page_index={page_index}&page_size={page_size}"
            f"&case_ward={quote(ward)}")
    text = post(session, "ashx/GetUpdQuery.ashx", data)
    return parse_json_lenient(text)


def enumerate_ward_seeds(session: requests.Session) -> list[tuple[str, str, str, str]]:
    """對 12 行政區做 GetUpdQuery 列舉，從每個案名解析 (段, 母號, 子號)。"""
    seeds = set()
    PAGE_SIZE = 100
    for ward in WARDS:
        try:
            count = get_upd_query_count(session, ward)
        except Exception as e:
            print(f"  [error] {ward} count: {e}", flush=True)
            continue
        pages = (count + PAGE_SIZE - 1) // PAGE_SIZE
        print(f"  {ward}: 共 {count} 案 ({pages} 頁)", flush=True)
        for p in range(1, pages + 1):
            try:
                cases = get_upd_query_page(session, ward, p, PAGE_SIZE)
            except Exception as e:
                print(f"    [error] {ward} p{p}: {e}", flush=True)
                continue
            before = len(seeds)
            for c in cases:
                for m in SECT_RE.findall(c.get("case_name", "")):
                    seeds.add((m[0], m[1], m[2], m[3] or "0"))
            print(f"    p{p}: {len(cases)} 案 → 新增 {len(seeds) - before} 種子",
                  flush=True)
    return sorted(seeds)


def extract_seeds() -> list[tuple[str, str, str, str]]:
    """從 uro_gov_taipei_cases/index.csv 抽 (ward, sect, mono, suno) 種子。"""
    seed_csv = SEED_ROOT / "index.csv"
    if not seed_csv.exists():
        print(f"  [warn] 種子來源不存在：{seed_csv}")
        return []
    seeds = set()
    with seed_csv.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            title = row.get("案件名稱", "")
            for m in SECT_RE.findall(title):
                ward, sect, mono, suno = m[0], m[1], m[2], m[3] or "0"
                seeds.add((ward, sect, mono, suno))
    return sorted(seeds)


def search_cases(session: requests.Session, sect: str, mono: str, suno: str) -> list[dict]:
    """POST Get_updcase_list.ashx → 案件清單。"""
    data = f"qitem=qland&sectstr={quote(sect)}&monobuf={mono}&sunobuf={suno or 0}"
    text = post(session, "ashx/Get_updcase_list.ashx", data)
    return parse_json_lenient(text)


def fetch_case_top(session: requests.Session, internal_case_id: str) -> dict:
    text = post(session, "ashx/get_project168_top.ashx", f"case_id={internal_case_id}")
    arr = parse_json_lenient(text)
    return arr[0] if arr else {}


def fetch_case_eighth(session: requests.Session, internal_case_id: str) -> list[dict]:
    text = post(session, "ashx/Get_project168_eighth.ashx", f"case_id={internal_case_id}")
    return parse_json_lenient(text)


def fetch_case_ten(session: requests.Session, internal_case_id: str) -> list[dict]:
    text = post(session, "ashx/Get_project168_ten.ashx",
                f"case_id={internal_case_id}&type=get")
    return parse_json_lenient(text)


def extract_internal_case_id(details_url: str) -> str | None:
    """從 details URL 抽出 r_progress_detail 的 case_id。"""
    if "r_progress_detail" not in details_url:
        return None
    parsed = urlparse(details_url)
    qs = parse_qs(parsed.query)
    return qs.get("case_id", [None])[0]


def _stream_download(session: requests.Session, url: str, dest: Path,
                     timeout: int = TIMEOUT) -> int:
    """共用串流下載：先寫 .partial、驗證 %PDF magic、改名。retry 3 次。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    last_err = None
    for attempt in range(1, RETRIES + 1):
        try:
            with session.get(url, headers=HEADERS, timeout=timeout, stream=True) as resp:
                resp.raise_for_status()
                size = 0
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                            size += len(chunk)
                with open(tmp, "rb") as f:
                    head = f.read(4)
                if head != b"%PDF":
                    raise RuntimeError(f"not a PDF (head={head!r}, size={size})")
                tmp.replace(dest)
                return size
        except Exception as e:
            last_err = e
            if attempt < RETRIES:
                time.sleep(2 ** attempt)
    if tmp.exists():
        tmp.unlink()
    raise RuntimeError(f"download failed: {last_err}")


def download_od_pdf(session: requests.Session, filename: str, dest: Path) -> int:
    """公告公文 PDF (DownloadODFile.ashx)。"""
    url = f"{BASE}/ashx/DownloadODFile.ashx?filename={quote(filename)}"
    return _stream_download(session, url, dest)


def download_ten_pdf(session: requests.Session, case_id: str, load_name: int,
                     dest: Path) -> int:
    """公開計畫書本體 (Get_project168_ten.ashx?type=download)。檔通常很大，timeout 拉長。"""
    url = (f"{BASE}/ashx/Get_project168_ten.ashx?type=download"
           f"&load_name={load_name}&case_id={case_id}")
    return _stream_download(session, url, dest, timeout=600)


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"cases": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def od_filename(od_docpath: str) -> str | None:
    """OD_DOCPATH 形如 '../ODrecords/案名_公展公告.pdf'，取 split('/')[2]。"""
    if not od_docpath:
        return None
    parts = od_docpath.split("/")
    return parts[2] if len(parts) >= 3 else parts[-1]


def short_date(iso: str) -> str:
    """'2025-03-21T00:00:00' → '2025-03-21'，None / 空白 → ''。"""
    if not iso:
        return ""
    return iso[:10]


def process_case(
    session: requests.Session,
    internal_case_id: str,
    external_case_id: str,
    case_record_in_state: dict | None,
    state: dict,
    counters: dict,
) -> dict | None:
    """處理單一案件：抓 top + eighth + ten，下載新 PDF，更新 state。"""
    print(f"  [case {internal_case_id}] external={external_case_id}", flush=True)
    try:
        top = fetch_case_top(session, internal_case_id)
        eighth = fetch_case_eighth(session, internal_case_id)
        ten = fetch_case_ten(session, internal_case_id)
    except Exception as e:
        print(f"    [error] fetch failed: {e}", flush=True)
        counters["case_failed"] += 1
        return None

    case_name = top.get("CASE_NAME") or top.get("case_name") or "(無案名)"
    # district 從 top 取不到時，從 eighth 或 ten 拿
    district = ""
    for src in (top, *(eighth or []), *(ten or [])):
        d = src.get("DISTRICT") or src.get("district")
        if d:
            district = d
            break
    if not district:
        district = "未分類"

    executor = top.get("EXE_NAME") or top.get("exe_name2") or ""
    place = top.get("PLACE") or ""

    record = case_record_in_state or {
        "case_id": internal_case_id,
        "external_case_id": external_case_id,
        "first_seen": dt.datetime.now().isoformat(timespec="seconds"),
    }
    record.update({
        "case_name": case_name,
        "district": district,
        "executor": executor,
        "place": place,
        "details_url": f"{BASE}/r_progress_detail.aspx?case_id={internal_case_id}",
        "top_meta": top,
        "last_seen": dt.datetime.now().isoformat(timespec="seconds"),
    })

    od_pdfs_state = {p["filename"]: p for p in record.get("od_pdfs", [])}
    ten_pdfs_state = {p["filename"]: p for p in record.get("ten_pdfs", [])}

    pdfs_dir = ROOT / "pdfs" / sanitize_filename(district, 20)

    # 公告公文 (eighth)
    new_od = []
    for od in eighth:
        fname = od_filename(od.get("OD_DOCPATH", ""))
        if not fname:
            continue
        post_date = short_date(od.get("OD_POSTDATE", ""))
        subject = (od.get("OD_SUBJECT") or "").strip()
        doc_no = (od.get("OD_DOCNO") or "").strip()
        # 本地路徑：{date}_{case_id}_{subject}_{原檔名}
        prefix_parts = [post_date or "0000-00-00", internal_case_id]
        if subject:
            prefix_parts.append(sanitize_filename(subject, 10))
        local_name = "_".join(prefix_parts) + "_" + sanitize_filename(fname, 80)
        if not local_name.lower().endswith(".pdf"):
            local_name += ".pdf"
        rel_path = Path("pdfs") / sanitize_filename(district, 20) / local_name
        local_path = ROOT / rel_path
        already = od_pdfs_state.get(fname)
        if already and (ROOT / already["local_path"]).exists():
            new_od.append(already)
            counters["od_skip"] += 1
            continue
        try:
            size = download_od_pdf(session, fname, local_path)
            entry = {
                "od_num": od.get("OD_NUM"),
                "post_date": post_date,
                "doc_no": doc_no,
                "subject": subject,
                "filename": fname,
                "local_path": str(rel_path),
                "size_bytes": size,
                "category": "公告公文",
            }
            new_od.append(entry)
            counters["od_new"] += 1
            print(f"    [+ od] {subject:6s} {post_date} ({size//1024}KB) {fname[:60]}",
                  flush=True)
        except Exception as e:
            print(f"    [error od] {fname[:60]}: {e}", flush=True)
            counters["od_failed"] += 1

    # 公開計畫書 (ten) — 預設只記 metadata；設 URO_GIS_DOWNLOAD_PLAN_BOOKS=1 才下載
    new_ten = []
    for idx, tp in enumerate(ten):
        fname = (tp.get("FileName") or "").strip()
        if not fname:
            continue
        start_date = (tp.get("StartDate") or "").replace("/", "-")
        end_date = (tp.get("EndDate") or "").replace("/", "-")
        already = ten_pdfs_state.get(fname)
        local_name = "_".join(filter(None, [start_date or "0000-00-00",
                                            internal_case_id, "公開計畫書"])) + "_" + sanitize_filename(fname, 80) + ".pdf"
        rel_path = Path("pdfs") / sanitize_filename(district, 20) / local_name

        entry = {
            "load_name": idx,  # ten 下載參數
            "post_date": start_date,
            "exhibit_start": start_date,
            "exhibit_end": end_date,
            "filename": fname,
            "local_path": str(rel_path) if (already and "size_bytes" in already) else "",
            "size_bytes": (already or {}).get("size_bytes", 0),
            "category": "公開計畫書",
        }

        # 已下載過就保留現有 entry
        if already and already.get("size_bytes") and (ROOT / already.get("local_path", "")).exists():
            new_ten.append({**already, "load_name": idx,
                             "exhibit_start": start_date, "exhibit_end": end_date})
            counters["ten_skip"] += 1
            continue

        if not DOWNLOAD_PLAN_BOOKS:
            new_ten.append(entry)  # 只記 metadata
            counters["ten_meta_only"] += 1
            continue

        # 真的要下載 (環境變數啟用)
        # 磁碟空間檢查：低於 MIN_FREE_GB 就 pause 等 iCloud 上傳
        free_gb = shutil.disk_usage(ROOT).free / 1e9
        while free_gb < MIN_FREE_GB:
            print(f"    [pause] 磁碟剩 {free_gb:.1f}GB < {MIN_FREE_GB}GB，等 60s iCloud 上傳...",
                  flush=True)
            time.sleep(60)
            free_gb = shutil.disk_usage(ROOT).free / 1e9

        local_path = ROOT / rel_path
        try:
            size = download_ten_pdf(session, internal_case_id, idx, local_path)
            entry["local_path"] = str(rel_path)
            entry["size_bytes"] = size
            new_ten.append(entry)
            counters["ten_new"] += 1
            counters["ten_since_pause"] += 1
            print(f"    [+ten] 公展計畫書 ({size//1024//1024}MB, 剩 {free_gb:.1f}GB) {fname[:50]}",
                  flush=True)
            # 每 PLAN_BOOK_BATCH 本就 pause
            if counters["ten_since_pause"] >= PLAN_BOOK_BATCH:
                print(f"    [pause] 已下載 {PLAN_BOOK_BATCH} 本計畫書，sleeping {PLAN_BOOK_PAUSE}s 讓 iCloud 上傳...",
                      flush=True)
                time.sleep(PLAN_BOOK_PAUSE)
                counters["ten_since_pause"] = 0
        except Exception as e:
            entry["local_path"] = ""
            entry["size_bytes"] = 0
            new_ten.append(entry)  # 仍記 metadata
            print(f"    [error ten] {fname[:50]}: {e}", flush=True)
            counters["ten_failed"] += 1

    record["od_pdfs"] = new_od
    record["ten_pdfs"] = new_ten

    # 寫案件 metadata JSON
    case_json_path = ROOT / "cases" / f"{internal_case_id}.json"
    case_json_path.parent.mkdir(parents=True, exist_ok=True)
    case_json_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    record["local_metadata_path"] = f"cases/{internal_case_id}.json"

    state["cases"][internal_case_id] = record
    save_state(state)
    return record


def build_index(state: dict) -> int:
    """重建 index.csv + index.md。回傳 row 數。"""
    rows = []
    for cid, rec in state.get("cases", {}).items():
        case_name = rec.get("case_name", "")
        district = rec.get("district", "")
        details_url = rec.get("details_url", "")
        # 公告公文
        for pdf in rec.get("od_pdfs", []):
            label = " ".join(filter(None, [pdf.get("subject", ""),
                                            pdf.get("doc_no", "")]))
            if not label:
                label = pdf.get("filename", "")[:60]
            source_url = (
                f"{BASE}/ashx/DownloadODFile.ashx?filename={quote(pdf.get('filename',''))}"
            )
            rows.append({
                "類別": "公告公文",
                "案件序號": cid,
                "公告日期": pdf.get("post_date", ""),
                "案件名稱": case_name,
                "文件標籤": label,
                "PDF 本地路徑": pdf.get("local_path", ""),
                "PDF 來源連結": source_url,
                "詳情頁連結": details_url,
            })
        # 公開計畫書
        for pdf in rec.get("ten_pdfs", []):
            ex_start = pdf.get("exhibit_start", "") or pdf.get("post_date", "")
            ex_end = pdf.get("exhibit_end", "")
            label = f"公展期 {ex_start} ~ {ex_end}".strip()
            source_url = (
                f"{BASE}/ashx/Get_project168_ten.ashx?type=download"
                f"&load_name={pdf.get('load_name', 0)}&case_id={cid}"
            )
            rows.append({
                "類別": "公開計畫書",
                "案件序號": cid,
                "公告日期": ex_start,
                "案件名稱": case_name,
                "文件標籤": label + " " + pdf.get("filename", "")[:30],
                "PDF 本地路徑": pdf.get("local_path", ""),  # 可能為空 (metadata-only)
                "PDF 來源連結": source_url,
                "詳情頁連結": details_url,
            })

    rows.sort(key=lambda r: (r["類別"], r["公告日期"] or "0000-00-00",
                              r["案件序號"], r["文件標籤"]))

    cols = ["類別", "案件序號", "公告日期", "案件名稱", "文件標籤",
            "PDF 本地路徑", "PDF 來源連結", "詳情頁連結"]
    with INDEX_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    # index.md
    today = dt.date.today().isoformat()
    by_cat = {}
    for r in rows:
        by_cat.setdefault(r["類別"], []).append(r)
    md = [
        "# 都更雲端 GIS — 公告公文與公開計畫書",
        "",
        f"最後更新：{today}",
        f"共 {len(rows)} 筆 PDF / {len(state.get('cases', {}))} 個案件",
        "",
        "## 統計",
        "",
        "| 類別 | 文件數 |",
        "| --- | --- |",
    ]
    for cat, items in sorted(by_cat.items()):
        md.append(f"| {cat} | {len(items)} |")
    md.append("")
    for cat, items in sorted(by_cat.items()):
        md += [f"## {cat}", "",
                "| 公告日期 | 案件序號 | 文件 | 案件名稱 |",
                "| --- | --- | --- | --- |"]
        for r in sorted(items, key=lambda x: x["公告日期"] or "0000-00-00", reverse=True):
            title = (r["案件名稱"] or "")[:60].replace("|", "\\|")
            label = (r["文件標籤"] or "")[:40].replace("|", "\\|")
            pdf_link = f"[📄]({r['PDF 本地路徑']})" if r["PDF 本地路徑"] else "—"
            md.append(f"| {r['公告日期'] or '—'} | {r['案件序號']} | {pdf_link} {label} | {title} |")
        md.append("")

    INDEX_MD.write_text("\n".join(md) + "\n", encoding="utf-8")
    return len(rows)


def main() -> int:
    print(f"Archive: {ROOT}")
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "cases").mkdir(exist_ok=True)
    (ROOT / "pdfs").mkdir(exist_ok=True)

    state = load_state()
    session = requests.Session()

    seeds_set = set(extract_seeds())
    print(f"從 uro_gov_taipei_cases 抽出 {len(seeds_set)} 個 (行政區, 段, 母號, 子號) 種子")
    if FULL_SWEEP:
        print("\n=== URO_GIS_FULL_SWEEP=1：對 12 行政區做 GetUpdQuery 列舉 ===")
        ward_seeds = enumerate_ward_seeds(session)
        before = len(seeds_set)
        seeds_set.update(ward_seeds)
        print(f"行政區掃描補入 {len(seeds_set) - before} 個新種子；總計 {len(seeds_set)} 個\n")
    else:
        print()
    seeds = sorted(seeds_set)

    counters = {
        "case_new": 0, "case_skip": 0, "case_failed": 0,
        "od_new": 0, "od_skip": 0, "od_failed": 0,
        "ten_new": 0, "ten_skip": 0, "ten_failed": 0, "ten_meta_only": 0,
        "ten_since_pause": 0,
        "search_failed": 0,
    }

    seen_internal = set()  # 避免重複處理同一案件
    for i, (ward, sect, mono, suno) in enumerate(seeds, 1):
        print(f"[{i}/{len(seeds)}] 查 {ward} {sect} {mono}-{suno}", flush=True)
        try:
            results = search_cases(session, sect, mono, suno)
        except Exception as e:
            print(f"    [error] search 失敗: {e}", flush=True)
            counters["search_failed"] += 1
            continue
        if not results:
            print(f"    (無案件)", flush=True)
            continue
        for case in results:
            details = case.get("details", "")
            internal = extract_internal_case_id(details)
            if not internal:
                continue  # 自行劃定核准單元，跳過
            if internal in seen_internal:
                continue
            seen_internal.add(internal)
            ext_cid = case.get("case_id", "")
            existing = state["cases"].get(internal)
            # 簡單去重：同 case_id 且已抓過，先跳過詳情查詢；
            # 但仍把現有資料保留在 index 裡 (build_index 會讀 state)
            # 為了增量檢查新文件，每次都重抓 eighth/ten
            try:
                rec = process_case(session, internal, ext_cid, existing, state, counters)
                if rec is not None:
                    if existing is None:
                        counters["case_new"] += 1
                    else:
                        counters["case_skip"] += 1
            except Exception as e:
                print(f"    [error] case {internal}: {e}", flush=True)
                counters["case_failed"] += 1

    save_state(state)
    n_index = build_index(state)

    print("\n========== 總結 ==========")
    print(f"處理種子數: {len(seeds)}")
    print(f"  search 失敗: {counters['search_failed']}")
    print(f"案件: 新增 {counters['case_new']} / 已知 {counters['case_skip']} / 失敗 {counters['case_failed']}")
    print(f"公告公文 PDF: 新下載 {counters['od_new']} / 略過 {counters['od_skip']} / 失敗 {counters['od_failed']}")
    if DOWNLOAD_PLAN_BOOKS:
        print(f"公開計畫書 PDF: 新下載 {counters['ten_new']} / 略過 {counters['ten_skip']} / 失敗 {counters['ten_failed']}")
    else:
        print(f"公開計畫書 PDF (僅 metadata，未下載): 新增 {counters['ten_meta_only']} / 略過 {counters['ten_skip']}")
        print(f"  → 設 URO_GIS_DOWNLOAD_PLAN_BOOKS=1 才會下載 (單檔常 100MB-500MB)")
    print(f"index.csv 共 {n_index} 筆")
    print(f"  → {INDEX_CSV}")
    print(f"  → {INDEX_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
