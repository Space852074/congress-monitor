# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import importlib
import json
import sqlite3
import sys
import traceback
from datetime import datetime, timedelta
from hashlib import sha1
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlunparse

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "data" / "congress.db"
STATIC_DIR = ROOT_DIR / "dashboard" / "static"
VALID_CHAMBERS = ("house", "senate")

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def normalize_link(url):
    url = (url or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower().replace("www.", "")
    path = (parsed.path or "").rstrip("/")
    return urlunparse((scheme, netloc, path, "", parsed.query, ""))


def discover_committees(chamber):
    chamber = (chamber or "").strip().lower()
    if chamber not in VALID_CHAMBERS:
        raise ValueError(f"Unsupported chamber: {chamber}")
    chamber_dir = ROOT_DIR / "committees" / chamber
    modules = {}
    for file in sorted(chamber_dir.glob("*.py")):
        if file.stem.startswith("_"):
            continue
        modules[file.stem] = f"committees.{chamber}.{file.stem}"
    return modules


def call_runner(run_committee):
    try:
        items = run_committee(existing_links=set())
    except TypeError as exc:
        if "unexpected keyword argument" in str(exc):
            items = run_committee()
        else:
            raise
    if not isinstance(items, list):
        raise TypeError("run_committee must return list")
    return items


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS committee_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chamber TEXT NOT NULL,
            committee_slug TEXT NOT NULL,
            committee_en TEXT,
            committee_cn TEXT,
            category TEXT,
            title TEXT NOT NULL,
            summary TEXT,
            sort_date TEXT,
            display_date TEXT,
            link TEXT,
            source_key TEXT NOT NULL UNIQUE,
            raw_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_items_date ON committee_items(sort_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_items_chamber ON committee_items(chamber)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_items_committee ON committee_items(committee_slug)")
        conn.commit()


def normalize_item(item, chamber_slug, committee_slug):
    chamber_name = (item.get("chamber") or chamber_slug.title()).strip()
    if chamber_name.lower() == "house":
        chamber_name = "House"
    elif chamber_name.lower() == "senate":
        chamber_name = "Senate"

    committee_en = (item.get("committee_en") or "").strip()
    committee_cn = (item.get("committee_cn") or item.get("committee_zh") or "").strip()
    category = (item.get("category") or item.get("category_en") or "").strip()
    title = (item.get("title") or "").strip()
    summary = (item.get("summary") or "").strip()
    sort_date = (item.get("sort_date") or "").strip()
    display_date = (item.get("date") or "").strip()
    link = normalize_link(item.get("link") or "")

    key_seed = "|".join([sort_date, chamber_name, committee_slug, category, title, link])
    source_key = sha1(key_seed.encode("utf-8", errors="ignore")).hexdigest()

    now_text = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "chamber": chamber_name,
        "committee_slug": committee_slug,
        "committee_en": committee_en,
        "committee_cn": committee_cn,
        "category": category,
        "title": title,
        "summary": summary,
        "sort_date": sort_date,
        "display_date": display_date,
        "link": link,
        "source_key": source_key,
        "raw_json": json.dumps(item, ensure_ascii=False),
        "created_at": now_text,
        "updated_at": now_text,
    }


def upsert_items(rows):
    if not rows:
        return 0

    sql = """
    INSERT INTO committee_items (
        chamber, committee_slug, committee_en, committee_cn, category,
        title, summary, sort_date, display_date, link, source_key, raw_json, created_at, updated_at
    ) VALUES (
        :chamber, :committee_slug, :committee_en, :committee_cn, :category,
        :title, :summary, :sort_date, :display_date, :link, :source_key, :raw_json, :created_at, :updated_at
    )
    ON CONFLICT(source_key) DO UPDATE SET
        chamber=excluded.chamber,
        committee_slug=excluded.committee_slug,
        committee_en=excluded.committee_en,
        committee_cn=excluded.committee_cn,
        category=excluded.category,
        title=excluded.title,
        summary=excluded.summary,
        sort_date=excluded.sort_date,
        display_date=excluded.display_date,
        link=excluded.link,
        raw_json=excluded.raw_json,
        updated_at=excluded.updated_at
    """

    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany(sql, rows)
        conn.commit()
    return len(rows)


def refresh_target(target):
    target = (target or "all").strip().lower()
    if target not in ("house", "senate", "all"):
        raise ValueError("target only supports house/senate/all")

    targets = VALID_CHAMBERS if target == "all" else (target,)
    summary = {
        "target": target,
        "started_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "fetched_items": 0,
        "saved_items": 0,
        "errors": [],
    }

    all_rows = []
    for chamber in targets:
        modules = discover_committees(chamber)
        for committee_slug, module_name in modules.items():
            try:
                module = importlib.import_module(module_name)
                runner = getattr(module, "run_committee", None)
                if not callable(runner):
                    raise AttributeError("run_committee not found")
                items = call_runner(runner)
                summary["fetched_items"] = summary["fetched_items"] + len(items)
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    row = normalize_item(item, chamber, committee_slug)
                    if row["title"]:
                        all_rows.append(row)
            except Exception as exc:
                summary["errors"].append({
                    "chamber": chamber,
                    "committee": committee_slug,
                    "error": str(exc),
                })

    summary["saved_items"] = upsert_items(all_rows)
    summary["finished_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    return summary


def query_stats():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    payload = {
        "total_items": 0,
        "today_items": 0,
        "last_update": "",
        "chambers": [],
    }
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT COUNT(1) AS cnt FROM committee_items").fetchone()
        payload["total_items"] = row["cnt"] if row else 0

        row = conn.execute("SELECT COUNT(1) AS cnt FROM committee_items WHERE sort_date = ?", (today,)).fetchone()
        payload["today_items"] = row["cnt"] if row else 0

        row = conn.execute("SELECT MAX(updated_at) AS last_update FROM committee_items").fetchone()
        payload["last_update"] = row["last_update"] if row and row["last_update"] else ""

        rows = conn.execute("SELECT chamber, COUNT(1) AS cnt FROM committee_items GROUP BY chamber ORDER BY cnt DESC").fetchall()
        payload["chambers"] = [{"chamber": r["chamber"], "count": r["cnt"]} for r in rows]
    return payload


def query_committees(chamber="", limit=40):
    limit = max(1, min(int(limit), 200))
    sql = """
    SELECT
        chamber,
        committee_slug,
        MAX(COALESCE(NULLIF(committee_cn, ""), committee_en, committee_slug)) AS committee_name,
        COUNT(1) AS cnt,
        MAX(sort_date) AS last_date
    FROM committee_items
    """
    params = []
    if chamber:
        sql = sql + " WHERE chamber = ?"
        params.append(chamber)
    sql = sql + " GROUP BY chamber, committee_slug ORDER BY cnt DESC LIMIT ?"
    params.append(limit)

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def query_items(chamber="", committee_slug="", days=30, limit=200):
    limit = max(1, min(int(limit), 500))
    days = max(1, min(int(days), 3650))
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    sql = """
    SELECT
        chamber, committee_slug, committee_en, committee_cn, category,
        title, summary, sort_date, display_date, link, updated_at
    FROM committee_items
    WHERE (sort_date = "" OR sort_date >= ?)
    """
    params = [cutoff]

    if chamber:
        sql = sql + " AND chamber = ?"
        params.append(chamber)
    if committee_slug:
        sql = sql + " AND committee_slug = ?"
        params.append(committee_slug)
    sql = sql + " ORDER BY sort_date DESC, updated_at DESC LIMIT ?"
    params.append(limit)

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


class AppHandler(BaseHTTPRequestHandler):
    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body, content_type="text/plain; charset=utf-8", status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, file_path, content_type):
        path = STATIC_DIR / file_path
        if not path.exists():
            self._send_bytes(b"Not Found", status=404)
            return
        self._send_bytes(path.read_bytes(), content_type=content_type)

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path == "/" or parsed.path == "/index.html":
            self._serve_file("index.html", "text/html; charset=utf-8")
            return

        if parsed.path == "/static/app.js":
            self._serve_file("app.js", "application/javascript; charset=utf-8")
            return

        if parsed.path == "/static/style.css":
            self._serve_file("style.css", "text/css; charset=utf-8")
            return

        if parsed.path == "/api/health":
            self._send_json({"ok": True, "db": str(DB_PATH)})
            return

        if parsed.path == "/api/stats":
            self._send_json(query_stats())
            return

        if parsed.path == "/api/committees":
            chamber = (query.get("chamber", [""])[0] or "").strip()
            limit = query.get("limit", ["40"])[0]
            self._send_json({"items": query_committees(chamber=chamber, limit=limit)})
            return

        if parsed.path == "/api/items":
            chamber = (query.get("chamber", [""])[0] or "").strip()
            committee = (query.get("committee", [""])[0] or "").strip()
            days = query.get("days", ["30"])[0]
            limit = query.get("limit", ["200"])[0]
            payload = query_items(chamber=chamber, committee_slug=committee, days=days, limit=limit)
            self._send_json({"items": payload})
            return

        if parsed.path == "/api/refresh":
            target = (query.get("target", ["all"])[0] or "all").strip()
            result = refresh_target(target)
            self._send_json(result)
            return

        self._send_bytes(b"Not Found", status=404)

    def log_message(self, format, *args):
        now_text = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now_text}] {self.address_string()} {format % args}")


def run_server(host, port):
    init_db()
    server = ThreadingHTTPServer((host, int(port)), AppHandler)
    print(f"Dashboard server running on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Server stopped by keyboard interrupt")
    finally:
        server.server_close()


def build_parser():
    parser = argparse.ArgumentParser(description="Local US Congress committee dashboard")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="Run local dashboard server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--bootstrap", action="store_true", help="Refresh before serving")

    refresh = sub.add_parser("refresh", help="Refresh database from committee sources")
    refresh.add_argument("--target", default="all", choices=["house", "senate", "all"] )

    sub.add_parser("initdb", help="Create local database schema")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "initdb":
            init_db()
            print(f"Initialized database: {DB_PATH}")
            return 0

        if args.command == "refresh":
            init_db()
            result = refresh_target(args.target)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        host = "127.0.0.1"
        port = 8765
        bootstrap = False
        if args.command == "serve":
            host = args.host
            port = args.port
            bootstrap = args.bootstrap

        init_db()
        if bootstrap:
            result = refresh_target("all")
            print(json.dumps(result, ensure_ascii=False, indent=2))
        run_server(host, port)
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
