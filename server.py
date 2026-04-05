#!/usr/bin/env python3
"""Static file server with DELETE, POST /refresh, and GET /status support."""

import html as _html
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

# ---------------------------------------------------------------------------
# Save discovery & registry
# ---------------------------------------------------------------------------

_OOTP_SEARCH = [
    (
        Path.home() / "Library/Containers",
        "com.ootpdevelopments.ootp*/Data/Application Support/"
        "Out of the Park Developments/OOTP Baseball */saved_games",
    ),
    (
        Path.home() / "Library/Application Support",
        "Out of the Park Developments/OOTP Baseball */saved_games",
    ),
]

_running_imports: dict = {}  # save_name -> {"proc": Popen, "log": [str]}
_running_jobs: dict = {}    # job_id -> {"proc": Popen, "log": [str], "skill": str, "args": str}
_jobs_lock = threading.Lock()


def _stream_output(proc, log):
    """Read subprocess stdout into log list (runs in a daemon thread)."""
    try:
        for line in proc.stdout:
            log.append(line.decode("utf-8", errors="replace").rstrip())
    except Exception:
        pass


def _find_saves_dirs():
    for root, pattern in _OOTP_SEARCH:
        if root.is_dir():
            yield from root.glob(pattern)


def _discover_save_names():
    """Return {save_name: lg_dir_path_str} for all discoverable .lg saves."""
    found = {}
    for saves_dir in _find_saves_dirs():
        for lg_dir in saves_dir.glob("*.lg"):
            name = lg_dir.stem
            if not name or lg_dir.name == ".lg":
                continue
            if name not in found:
                found[name] = str(lg_dir)
    return found


def _load_saves_registry():
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    from shared_css import load_saves_registry
    return load_saves_registry()


def _job_is_running(entry):
    proc = entry.get("proc")
    if proc is not None:
        return proc.poll() is None
    return not entry.get("done", False)


def get_jobs_data():
    with _jobs_lock:
        snapshot = list(_running_jobs.items())
    jobs = {}
    for job_id, entry in snapshot:
        jobs[job_id] = {
            "skill": entry["skill"],
            "args": entry["args"],
            "log": list(entry["log"]),
            "running": _job_is_running(entry),
            "file_path": entry.get("file_path"),
        }
    return jobs


def _save_registry(registry):
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    from shared_css import get_saves_path
    get_saves_path().write_text(json.dumps(registry, indent=2))


def _get_csv_mtime(csv_path):
    """Return ISO timestamp of most recently modified CSV file, or None."""
    import glob as _glob
    if not csv_path:
        return None
    files = _glob.glob(os.path.join(csv_path, "*.csv"))
    if not files:
        return None
    from datetime import datetime
    max_mtime = max(os.path.getmtime(f) for f in files)
    return datetime.fromtimestamp(max_mtime).strftime("%Y-%m-%dT%H:%M:%S")


def get_saves_data():
    registry = _load_saves_registry()
    imported = registry.get("saves", {})
    active = registry.get("active")

    discovered = _discover_save_names()
    not_imported = {name: path for name, path in discovered.items() if name not in imported}

    running = []
    logs = {}
    for name, entry in _running_imports.items():
        if entry["proc"].poll() is None:
            running.append(name)
        logs[name] = list(entry["log"])  # snapshot to avoid race with reader thread

    # Enrich each save with csv_mtime so the frontend can detect new CSV exports
    enriched = {}
    for name, info in imported.items():
        enriched[name] = dict(info)
        enriched[name]["csv_mtime"] = _get_csv_mtime(info.get("csv_path"))

    return {
        "active": active,
        "saves": enriched,
        "discovered": not_imported,
        "running": running,
        "logs": logs,
    }


# ---------------------------------------------------------------------------
# Status checks
# ---------------------------------------------------------------------------

def _check(name, ok, detail, fix=None):
    return {"name": name, "ok": ok, "detail": detail, "fix": fix}


def check_python():
    v = sys.version.split()[0]
    return _check("Python", True, f"Python {v} ({sys.executable})")


def check_venv():
    venv = ROOT / ".venv"
    if not venv.exists():
        return _check("Virtual env", False, ".venv not found",
                      "python3 -m venv .venv && .venv/bin/pip install -r requirements.txt")
    return _check("Virtual env", True, str(venv))


def _is_sqlite():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return True  # SQLite is the default when no .env exists
    for line in env_path.read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().lower().startswith("sqlite")
    return True  # no DATABASE_URL line → default to SQLite


def check_packages():
    pkgs = ["pandas", "sqlalchemy", "dotenv"]
    if not _is_sqlite():
        pkgs.append("psycopg2")
    missing = []
    for pkg in pkgs:
        try:
            importlib.import_module(pkg)
        except ImportError:
            missing.append(pkg if pkg != "dotenv" else "python-dotenv")
    if missing:
        return _check("Python packages", False,
                      f"Missing: {', '.join(missing)}",
                      ".venv/bin/pip install -r requirements.txt")
    installed = "pandas, sqlalchemy, python-dotenv"
    if not _is_sqlite():
        installed += ", psycopg2-binary"
    return _check("Python packages", True, installed)


def check_postgres():
    result = subprocess.run(
        ["pg_isready"], capture_output=True, text=True, timeout=3
    )
    if result.returncode != 0:
        return _check("PostgreSQL", False,
                      result.stdout.strip() or "Not accepting connections",
                      "brew install postgresql@14 && brew services start postgresql@14")
    ver_result = subprocess.run(
        ["psql", "--no-psqlrc", "-U", "postgres", "-c", "SELECT version();",
         "-t", "-A", "--csv"],
        capture_output=True, text=True, timeout=3
    )
    detail = result.stdout.strip()
    if ver_result.returncode == 0:
        version_line = ver_result.stdout.strip().split(",")[0]
        detail = version_line[:60] if version_line else detail
    return _check("PostgreSQL", True, detail)


def check_claude():
    path = shutil.which("claude")
    if not path:
        for candidate in [
            Path.home() / ".local/bin/claude",
            Path("/usr/local/bin/claude"),
        ]:
            if candidate.exists():
                path = str(candidate)
                break
    if not path:
        return _check("Claude CLI", False, "Not found in PATH",
                      "npm install -g @anthropic-ai/claude-code  "
                      "# or see claude.ai/code")
    result = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=5)
    version = result.stdout.strip() or result.stderr.strip() or "found"
    return _check("Claude CLI", True, f"{version}  ({path})")


def check_env_file():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return _check(".env config", True,
                      "Not present — using SQLite default (optional)")
    return _check(".env config", True, str(env_path))


def check_saves():
    registry = _load_saves_registry()
    imported = registry.get("saves", {})
    if not imported:
        return _check("OOTP saves", False, "No saves imported yet",
                      "./import.sh list   # then: ./import.sh <SaveName>")
    active = registry.get("active")
    count = len(imported)
    detail = f"{count} save{'s' if count != 1 else ''} imported"
    if active:
        detail += f"  •  Active: {active}"
    return _check("OOTP saves", True, detail)


def check_database():
    registry = _load_saves_registry()
    imported = registry.get("saves", {})
    active = registry.get("active")

    if _is_sqlite():
        db_dir = ROOT / "db"
        if not db_dir.exists():
            return _check("OOTP database", False, "No SQLite databases found",
                          "./import.sh <SaveName>")
        db_files = sorted(db_dir.glob("*.db"))
        if not db_files:
            return _check("OOTP database", False, "No SQLite databases found",
                          "./import.sh <SaveName>")
        detail = ", ".join(f.stem for f in db_files)
        if active and active in imported:
            last = imported[active].get("last_import")
            if last:
                detail += f"  •  Last import: {last}"
        return _check("OOTP database", True, detail)

    # PostgreSQL path — only reached when _is_sqlite() is False, meaning .env exists
    # with a non-sqlite DATABASE_URL
    env_path = ROOT / ".env"
    database_url = None
    for line in env_path.read_text().splitlines():
        key = line.split("=", 1)[0] if "=" in line else ""
        if key in ("DATABASE_URL", "POSTGRES_URL"):
            database_url = line.split("=", 1)[1].strip()
            break
    if not database_url:
        return _check("OOTP database", False, "DATABASE_URL not set in .env", None)

    try:
        if str(SRC) not in sys.path:
            sys.path.insert(0, str(SRC))
        from sqlalchemy import create_engine, text
        from dotenv import load_dotenv
        load_dotenv(env_path)
        engine = create_engine(database_url.rstrip("/") + "/postgres")
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT datname FROM pg_database "
                "WHERE datname LIKE '%_cbl' OR datname LIKE '%_lg' "
                "ORDER BY datname"
            )).fetchall()
        db_names = [r[0] for r in rows]
        if not db_names:
            return _check("OOTP database", False, "No OOTP database found",
                          "./import.sh <SaveName>")
        detail = ", ".join(db_names)
        if active and active in imported:
            last = imported[active].get("last_import")
            if last:
                detail += f"  •  Last import: {last}"
        return _check("OOTP database", True, detail)
    except Exception as e:
        return _check("OOTP database", False, str(e)[:120],
                      "./import.sh <SaveName>")


def run_all_checks():
    checks = [
        check_python(),
        check_venv(),
        check_packages(),
    ]
    if not _is_sqlite():
        checks.append(check_postgres())
    checks += [
        check_claude(),
        check_env_file(),
        check_saves(),
        check_database(),
    ]
    return checks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_target(path_str):
    """Resolve a URL path to an absolute Path inside ROOT, or return None."""
    target = (ROOT / path_str.lstrip("/")).resolve()
    try:
        target.relative_to(ROOT)
        return target
    except ValueError:
        return None


def _read_meta(content, name):
    m = re.search(rf'<meta name="{name}" content="([^"]*)"', content)
    return _html.unescape(m.group(1)) if m else None


def _extract_analyses(content):
    return re.findall(
        r'<!-- ANALYSIS:START -->(.*?)<!-- ANALYSIS:END -->',
        content, re.DOTALL
    )


def _reinject_analyses(content, blocks):
    it = iter(blocks)
    def replacer(m):
        block = next(it, None)
        if block is None:
            return m.group(0)
        return f'<!-- ANALYSIS:START -->{block}<!-- ANALYSIS:END -->'
    return re.sub(
        r'<!-- ANALYSIS:START --><!-- [A-Z_:]+ --><!-- ANALYSIS:END -->',
        replacer, content
    )


def _json_response(handler, data, code=200):
    payload = json.dumps(data).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


REPORTS_ROOT = ROOT / "reports"


def _reports_search_save_roots(save_param, all_saves):
    if all_saves:
        if not REPORTS_ROOT.is_dir():
            return []
        return sorted(p for p in REPORTS_ROOT.iterdir() if p.is_dir())
    registry = _load_saves_registry()
    name = (save_param or "").strip() or (registry.get("active") or "")
    if not name:
        return []
    root = REPORTS_ROOT / name
    try:
        root.resolve().relative_to(REPORTS_ROOT.resolve())
    except ValueError:
        return []
    return [root] if root.is_dir() else []


def _is_under_reports(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPORTS_ROOT.resolve())
        return True
    except ValueError:
        return False


def _handle_reports_search(handler):
    from urllib.parse import urlparse, parse_qs, unquote

    parsed = urlparse(handler.path)
    qs = parse_qs(parsed.query)
    q = (qs.get("q") or [""])[0].strip()
    if not q:
        _json_response(handler, {"results": [], "error": "missing q"}, 400)
        return
    save_param = unquote((qs.get("save") or [""])[0].strip())
    all_saves = (qs.get("all_saves") or [""])[0].strip().lower() in ("1", "true", "yes")

    tokens = [t.lower() for t in q.split() if t]
    if not tokens:
        _json_response(handler, {"results": [], "error": "empty query"}, 400)
        return

    roots = _reports_search_save_roots(save_param, all_saves)
    results = []
    max_results = 50
    reports_resolved = REPORTS_ROOT.resolve()

    for root in roots:
        if len(results) >= max_results:
            break
        if not root.is_dir():
            continue
        for sidecar in root.rglob("*.search.json"):
            if len(results) >= max_results:
                break
            try:
                if not sidecar.is_file():
                    continue
                if not _is_under_reports(sidecar):
                    continue
                name = sidecar.name
                if not name.endswith(".search.json"):
                    continue
                html_name = name[: -len(".search.json")] + ".html"
                html_path = (sidecar.parent / html_name).resolve()
                if not html_path.is_file():
                    continue
                if not _is_under_reports(html_path):
                    continue
                raw = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
            if not isinstance(raw, dict):
                continue
            title = raw.get("title") or ""
            text = raw.get("text") or ""
            if not isinstance(title, str):
                title = str(title)
            if not isinstance(text, str):
                text = str(text)
            hay = text.lower()
            if not all(t in hay for t in tokens):
                continue

            rel = html_path.relative_to(ROOT.resolve())
            url_path = "/".join(rel.parts)
            cat = ""
            try:
                rp = html_path.relative_to(reports_resolved)
                parts = rp.parts
                if len(parts) >= 2:
                    cat = parts[1]
            except ValueError:
                pass

            results.append({
                "path": url_path,
                "title": title or html_path.stem.replace("_", " ").replace("-", " "),
                "category": cat,
            })

    _json_response(handler, {"results": results})

# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        if self.path == "/status":
            _json_response(self, run_all_checks())
        elif self.path == "/saves":
            _json_response(self, get_saves_data())
        elif self.path.startswith("/saves/my-team-candidates"):
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            save_name = (qs.get("save") or [""])[0].strip()
            self._handle_my_team_candidates(save_name)
        elif self.path == "/git-status":
            status_file = ROOT / ".update-status"
            result = {"updates_available": False}
            if status_file.exists():
                try:
                    result = json.loads(status_file.read_text())
                except (OSError, json.JSONDecodeError):
                    pass
            _json_response(self, result)
        elif self.path == "/reports/jobs":
            _json_response(self, get_jobs_data())
        elif self.path.startswith("/reports/jobs/") and self.path.endswith("/stream"):
            job_id = self.path[len("/reports/jobs/"):-len("/stream")]
            self._handle_job_stream(job_id)
        elif self.path.startswith("/reports/search"):
            _handle_reports_search(self)
        else:
            super().do_GET()

    def do_DELETE(self):
        target = _safe_target(self.path)
        if not target:
            self.send_error(403, "Forbidden")
            return
        if not target.exists():
            self.send_error(404, "Not found")
            return
        if not target.is_file():
            self.send_error(400, "Not a file")
            return
        target.unlink()
        if target.suffix.lower() == ".html":
            sc = target.with_name(target.stem + ".search.json")
            if sc.is_file():
                try:
                    sc.unlink()
                except OSError:
                    pass
        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length)) if length else {}
        except (json.JSONDecodeError, ValueError):
            self.send_error(400, "Invalid JSON")
            return

        if self.path == "/refresh":
            self._handle_refresh(body)
        elif self.path == "/saves/import":
            self._handle_import(body)
        elif self.path == "/saves/set-active":
            self._handle_set_active(body)
        elif self.path == "/saves/set-my-team":
            self._handle_set_my_team(body)
        elif self.path == "/saves/clear-log":
            self._handle_clear_log(body)
        elif self.path == "/reports/generate":
            self._handle_generate(body)
        elif self.path == "/reports/clear-job":
            self._handle_clear_job(body)
        else:
            self.send_error(404)

    def _handle_import(self, body):
        save_name = body.get("save", "").strip()
        if not save_name:
            self._respond(400, "Missing save name")
            return

        # Reject if already running
        entry = _running_imports.get(save_name)
        if entry and entry["proc"].poll() is None:
            self._respond(409, "Import already running")
            return

        log = []
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        proc = subprocess.Popen(
            ["bash", str(ROOT / "import.sh"), save_name],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
        threading.Thread(target=_stream_output, args=(proc, log), daemon=True).start()
        _running_imports[save_name] = {"proc": proc, "log": log}
        self._respond(202, "started")

    def _handle_generate(self, body):
        skill = body.get("skill", "").strip()
        args = body.get("args", "").strip()
        # lineup-optimizer has all-optional args; allow empty string through
        args_optional = skill in ("lineup-optimizer",)
        if not skill or (not args and not args_optional):
            self._respond(400, "Missing skill or args")
            return
        job_id = f"{skill}-{int(time.time())}"
        log = []
        if skill == "adhoc":
            cost_footer = (
                "\n\nAfter answering, print this line on its own: "
                "`~ Model: claude-sonnet-4-6 | est. X–Y¢` "
                "replacing X–Y with your best cost estimate "
                "(2–4¢ for a simple lookup, 5–10¢ for moderate analysis, 10–20¢ for complex multi-table work)."
            )
            cmd_arg = args + cost_footer
        else:
            cmd_arg = f"/{skill} {args}".strip()
        proc = subprocess.Popen(
            ["claude", "-p", cmd_arg],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        threading.Thread(target=_stream_output, args=(proc, log), daemon=True).start()
        with _jobs_lock:
            _running_jobs[job_id] = {"proc": proc, "log": log, "skill": skill, "args": args}
        _json_response(self, {"job_id": job_id}, 202)

    def _handle_job_stream(self, job_id):
        entry = _running_jobs.get(job_id)
        if not entry:
            self.send_error(404, "Job not found")
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        sent = 0
        try:
            while True:
                log = entry["log"]
                while sent < len(log):
                    line = log[sent]
                    self.wfile.write(f"data: {json.dumps(line)}\n\n".encode())
                    self.wfile.flush()
                    sent += 1

                if not _job_is_running(entry):
                    # Job finished — drain any remaining lines, then signal done
                    log = entry["log"]
                    while sent < len(log):
                        line = log[sent]
                        self.wfile.write(f"data: {json.dumps(line)}\n\n".encode())
                        self.wfile.flush()
                        sent += 1
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                    return

                time.sleep(0.1)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # Client disconnected

    def _handle_clear_job(self, body):
        job_id = body.get("job_id", "").strip()
        with _jobs_lock:
            _running_jobs.pop(job_id, None)
        self._respond(200, "ok")

    def _handle_clear_log(self, body):
        save_name = body.get("save", "").strip()
        if save_name in _running_imports:
            del _running_imports[save_name]
        self._respond(200, "ok")

    def _handle_set_active(self, body):
        save_name = body.get("save", "").strip()
        if not save_name:
            self._respond(400, "Missing save name")
            return
        registry = _load_saves_registry()
        if save_name not in registry.get("saves", {}):
            self._respond(404, "Save not found in registry")
            return
        registry["active"] = save_name
        _save_registry(registry)
        self._respond(200, "ok")

    def _handle_my_team_candidates(self, save_name):
        if not save_name:
            _json_response(self, {"error": "Missing save name"}, 400)
            return
        registry = _load_saves_registry()
        if save_name not in registry.get("saves", {}):
            _json_response(self, {"error": "Save not found"}, 404)
            return
        try:
            if str(SRC) not in sys.path:
                sys.path.insert(0, str(SRC))
            from sqlalchemy import create_engine, text
            from dotenv import load_dotenv
            env_path = ROOT / ".env"
            if env_path.exists():
                load_dotenv(env_path)
            db_name = registry["saves"][save_name]["db_name"]
            db_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or "sqlite"
            if db_url.lower().startswith("sqlite"):
                engine = create_engine(f"sqlite:///{ROOT / 'db' / db_name}.db")
            else:
                engine = create_engine(f"{db_url.rstrip('/')}/{db_name}")
            with engine.connect() as conn:
                rows = conn.execute(text("""
                    SELECT hm.human_manager_id, hm.team_id,
                           t.name, t.nickname, t.abbr
                    FROM human_managers hm
                    JOIN teams t ON t.team_id = hm.team_id
                    WHERE t.league_id = 203
                    ORDER BY t.abbr
                """)).fetchall()
            candidates = [
                dict(human_manager_id=r[0], team_id=r[1],
                     name=r[2], nickname=r[3], abbr=r[4])
                for r in rows
            ]
            # Auto-set if unambiguous
            auto_set = False
            if len(candidates) == 1 and not registry["saves"][save_name].get("my_team_id"):
                c = candidates[0]
                registry["saves"][save_name]["my_team_id"] = c["team_id"]
                registry["saves"][save_name]["my_team_abbr"] = c["abbr"]
                _save_registry(registry)
                auto_set = True
            _json_response(self, {"candidates": candidates, "auto_set": auto_set})
        except Exception as e:
            _json_response(self, {"error": str(e)}, 500)

    def _handle_set_my_team(self, body):
        save_name = body.get("save", "").strip()
        team_id = body.get("team_id")
        team_abbr = body.get("team_abbr", "").strip()
        if not save_name or not team_id:
            self._respond(400, "Missing save or team_id")
            return
        try:
            team_id_int = int(team_id)
        except (TypeError, ValueError):
            self._respond(400, "Invalid team_id")
            return
        registry = _load_saves_registry()
        if save_name not in registry.get("saves", {}):
            self._respond(404, "Save not found in registry")
            return
        registry["saves"][save_name]["my_team_id"] = team_id_int
        registry["saves"][save_name]["my_team_abbr"] = team_abbr
        _save_registry(registry)
        self._respond(200, "ok")

    def _handle_refresh(self, body):
        file_path = body.get("path", "")
        mode = body.get("mode", "data")

        target = _safe_target(file_path)
        if not target or not target.is_file():
            self._respond(404, "Report not found")
            return

        current = target.read_text()
        skill = _read_meta(current, "ootp-skill")
        args  = _read_meta(current, "ootp-args")
        save  = _read_meta(current, "ootp-save")

        if not skill or not args or not save:
            self._respond(400, "Report has no refresh metadata — regenerate it first")
            return

        job_id = f"refresh-{int(time.time() * 1000)}"
        log = []
        entry = {"skill": skill, "args": args, "log": log, "proc": None, "done": False, "file_path": file_path}
        with _jobs_lock:
            _running_jobs[job_id] = entry

        if mode == "full":
            # Back up the report; restore it if Claude fails so the file isn't lost
            backup = target.with_suffix(".bak")
            shutil.copy2(target, backup)
            target.unlink()  # force cache miss so the skill regenerates
            cmd = ["claude", "-p", f"/{skill} {args}"]
            proc = subprocess.Popen(
                cmd, cwd=str(ROOT),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            entry["proc"] = proc

            def _restore_on_failure():
                _stream_output(proc, log)
                if proc.returncode != 0 and not target.exists() and backup.exists():
                    shutil.move(str(backup), str(target))
                    log.append("Error: Claude job failed — original report restored.")
                else:
                    backup.unlink(missing_ok=True)

            threading.Thread(target=_restore_on_failure, daemon=True).start()
        else:
            analyses = _extract_analyses(current)
            target.unlink(missing_ok=True)
            kwargs_override = body.get("kwargs_override")

            def _run_in_thread():
                if str(SRC) not in sys.path:
                    sys.path.insert(0, str(SRC))
                try:
                    log.append(f"Regenerating {skill} report…")
                    new_path = self._run_data(skill, args, save, kwargs_override)
                    if analyses and new_path:
                        new_path_p = Path(new_path)
                        new_content = new_path_p.read_text(encoding="utf-8")
                        new_content = _reinject_analyses(new_content, analyses)
                        from report_write import write_report_html

                        write_report_html(new_path_p, new_content)
                    log.append(f"Done.")
                except Exception as e:
                    log.append(f"Error: {e}")
                finally:
                    entry["done"] = True

            threading.Thread(target=_run_in_thread, daemon=True).start()

        _json_response(self, {"job_id": job_id}, 202)

    def _run_data(self, skill, args, save, kwargs_override=None):
        if skill == "player-stats":
            from report import generate_player_report
            first, *rest = args.split()
            last = " ".join(rest)
            path, _ = generate_player_report(save, first, last)
            return path

        if skill == "player-rating":
            from ratings import generate_rating_report
            parts = args.split()
            first, last = parts[0], parts[1] if len(parts) > 1 else ""
            focus = parts[2:] if len(parts) > 2 else None
            path, _ = generate_rating_report(save, first, last, focus)
            return path

        if skill == "contract-extension":
            from contract_extension import generate_contract_extension_report
            first, *rest = args.split()
            last = " ".join(rest)
            path, _ = generate_contract_extension_report(save, first, last)
            if path is None:
                raise ValueError(
                    "Player not found on MLB roster for contract extension report"
                )
            return path

        if skill == "waiver-claim":
            from waiver_wire import generate_waiver_claim_report
            first, *rest = args.split()
            last = " ".join(rest)
            path, _ = generate_waiver_claim_report(save, first, last)
            if path is None:
                raise ValueError(
                    "Player not found for waiver claim report"
                )
            return path

        kw = kwargs_override or {}
        where  = kw.get("where_clause", "1=1")
        order  = kw.get("order_by")
        limit  = kw.get("limit", 25)

        if skill == "free-agents":
            from free_agents import generate_free_agents_report
            path, _ = generate_free_agents_report(
                save, args, where,
                join_clause=kw.get("join_clause", ""),
                order_by=order or "pr.rating_overall DESC",
                limit=limit,
                highlight=kw.get("highlight"),
            )
            return path

        if skill == "draft-targets":
            from draft_targets import generate_draft_targets_report
            path, _ = generate_draft_targets_report(
                save, args, where,
                order_by=order or "dr.rating_overall DESC",
                limit=limit,
            )
            return path

        if skill == "ifa-targets":
            from ifa_targets import generate_ifa_targets_report
            path, _ = generate_ifa_targets_report(
                save, args, where,
                order_by=order or "ir.rating_overall DESC",
                limit=limit,
            )
            return path

        if skill == "lineup-optimizer":
            import re as _re
            from lineup_optimizer import POS_STR_MAP, generate_lineup_report
            _lo_raw = (args or "").lower()
            _lo_hand = (
                "L" if any(w in _lo_raw for w in ("lhp", "lefty")) else
                "R" if any(w in _lo_raw for w in ("rhp", "righty")) else
                None
            )
            _lo_phil = next(
                (p for p in ("modern", "traditional", "platoon", "hot-hand") if p in _lo_raw),
                "platoon" if _lo_hand else "modern",
            )
            _lo_primary = any(w in _lo_raw for w in ("primary", "primary-only"))
            _lo_favor_offense = any(w in _lo_raw for w in ("favor-offense", "favor offense", "favour offense", "favour-offense"))

            # fatigue threshold: "fatigue 70" or "fatigue: 70"
            _fat_m = _re.search(r'fatigue\s*:?\s*(\d+)', _lo_raw)
            _lo_fatigue = int(_fat_m.group(1)) if _fat_m else None

            # forced bench: "<name> bench"
            _lo_forced_bench = [
                m.group(1).strip()
                for m in _re.finditer(r'([A-Za-z][A-Za-z\s\-\']+?)\s+bench(?:\b|$)', args or "", _re.I)
            ]

            # forced starts: "<name> starts [at <pos>]" or "<name> at <pos> starts"
            _lo_forced_starts = []
            for m in _re.finditer(
                r'([A-Za-z][A-Za-z\s\-\']+?)\s+(?:starts?\s+at\s+(\w+)|at\s+(\w+)\s+starts?|starts?)(?:\b|$)',
                args or "", _re.I
            ):
                _fs_name = m.group(1).strip()
                _fs_pos_str = (m.group(2) or m.group(3) or "").lower()
                _fs_pos = POS_STR_MAP.get(_fs_pos_str)
                _lo_forced_starts.append(dict(name=_fs_name, pos=_fs_pos))

            # excluded (without/excluding)
            _lo_excl = []
            for m in _re.finditer(
                r'(?:without|excluding)\s+([A-Za-z][A-Za-z\s\-\']+?)'
                r'(?=\s+(?:vs\b|modern|traditional|platoon|hot-hand|primary|fatigue|favor|favour|without|excluding)|,|$)',
                args or "", _re.I
            ):
                _lo_excl.append(m.group(1).strip())

            # Strip all override tokens to isolate team name
            _lo_stop_re = (r'(?:modern|traditional|platoon|hot-hand|favor-offense|favour-offense|vs\s+(?:lhp|rhp|lefty|righty)|'
                           r'lhp|rhp|lefty|righty|primary(?:-only)?|favor\s+offense|favour\s+offense|fatigue\s*:?\s*\d+|'
                           r'without\s+[A-Za-z][A-Za-z\s\-\']+|excluding\s+[A-Za-z][A-Za-z\s\-\']+|'
                           r'[A-Za-z][A-Za-z\s\-\']+?\s+bench|'
                           r'[A-Za-z][A-Za-z\s\-\']+?\s+(?:starts?\s+at\s+\w+|at\s+\w+\s+starts?|starts?))')
            _lo_team = _re.sub(_lo_stop_re, '', args or '', flags=_re.I).strip(" ,") or None

            path, _ = generate_lineup_report(
                save,
                team_query=_lo_team,
                philosophy=_lo_phil,
                opponent_hand=_lo_hand,
                primary_only=_lo_primary,
                forced_starts=_lo_forced_starts,
                forced_bench=_lo_forced_bench,
                fatigue_threshold=_lo_fatigue,
                excluded_names=_lo_excl,
                favor_offense=_lo_favor_offense,
            )
            if path is None:
                raise ValueError("Team not found or no batters available for lineup report")
            return path

        if skill == "trade-targets":
            from trade_targets import generate_trade_targets_report
            _reg = _load_saves_registry()
            _my_team_id = _reg.get("saves", {}).get(save, {}).get("my_team_id") or 10
            path, _ = generate_trade_targets_report(
                save, args,
                offered_where=kw.get("offered_where", "1=1"),
                target_where=kw.get("target_where", "1=1"),
                my_team_id=_my_team_id,
                mode=kw.get("mode", "offering"),
                target_join=kw.get("target_join", ""),
                order_by=order or "pr.rating_overall DESC",
                limit=limit,
                highlight=kw.get("highlight"),
            )
            return path

        raise ValueError(f"Unknown skill: {skill}")

    def _respond(self, code, body):
        payload = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        if args and str(args[1]) >= "400":
            super().log_message(fmt, *args)


if __name__ == "__main__":
    port = 8000
    print(f"OOTP Reports → http://localhost:{port}")
    ThreadingHTTPServer(("", port), Handler).serve_forever()
