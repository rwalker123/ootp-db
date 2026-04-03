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
    saves_json = ROOT / "saves.json"
    if saves_json.exists():
        return json.loads(saves_json.read_text())
    return {"saves": {}}


def get_jobs_data():
    jobs = {}
    for job_id, entry in _running_jobs.items():
        jobs[job_id] = {
            "skill": entry["skill"],
            "args": entry["args"],
            "log": list(entry["log"]),
            "running": entry["proc"].poll() is None,
        }
    return jobs


def _save_registry(registry):
    (ROOT / "saves.json").write_text(json.dumps(registry, indent=2))


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

    return {
        "active": active,
        "saves": imported,
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


def check_packages():
    missing = []
    for pkg in ("pandas", "sqlalchemy", "psycopg2", "dotenv"):
        try:
            importlib.import_module(pkg)
        except ImportError:
            missing.append(pkg if pkg != "dotenv" else "python-dotenv")
    if missing:
        return _check("Python packages", False,
                      f"Missing: {', '.join(missing)}",
                      ".venv/bin/pip install -r requirements.txt")
    return _check("Python packages", True, "pandas, sqlalchemy, psycopg2-binary, python-dotenv")


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
        return _check(".env config", False, ".env not found",
                      "cp .env.example .env  # then edit with your paths")
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
    env_path = ROOT / ".env"
    if not env_path.exists():
        return _check("OOTP database", False, ".env missing", None)
    postgres_url = None
    for line in env_path.read_text().splitlines():
        if line.startswith("POSTGRES_URL="):
            postgres_url = line.split("=", 1)[1].strip()
            break
    if not postgres_url:
        return _check("OOTP database", False, "POSTGRES_URL not set in .env", None)

    registry = _load_saves_registry()
    imported = registry.get("saves", {})

    try:
        sys.path.insert(0, str(SRC))
        from sqlalchemy import create_engine, text
        from dotenv import load_dotenv
        load_dotenv(env_path)
        db_url = os.environ.get("POSTGRES_URL", postgres_url)
        engine = create_engine(db_url + "/postgres")
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
        active = registry.get("active")
        if active and active in imported:
            last = imported[active].get("last_import")
            if last:
                detail += f"  •  Last import: {last}"
        return _check("OOTP database", True, detail)
    except Exception as e:
        return _check("OOTP database", False, str(e)[:120],
                      "./import.sh <SaveName>")


def run_all_checks():
    return [
        check_python(),
        check_venv(),
        check_packages(),
        check_postgres(),
        check_claude(),
        check_env_file(),
        check_saves(),
        check_database(),
    ]


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
        elif self.path == "/reports/jobs":
            _json_response(self, get_jobs_data())
        elif self.path.startswith("/reports/jobs/") and self.path.endswith("/stream"):
            job_id = self.path[len("/reports/jobs/"):-len("/stream")]
            self._handle_job_stream(job_id)
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
        if not skill or not args:
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
            cmd_arg = f"/{skill} {args}"
        proc = subprocess.Popen(
            ["claude", "-p", cmd_arg],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        threading.Thread(target=_stream_output, args=(proc, log), daemon=True).start()
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

                if entry["proc"].poll() is not None:
                    # Process finished — drain any remaining lines, then signal done
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
        if job_id in _running_jobs:
            del _running_jobs[job_id]
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

        if mode == "full":
            self._run_full(skill, args)
            return

        analyses = _extract_analyses(current)
        target.unlink()

        sys.path.insert(0, str(SRC))
        try:
            new_path = self._run_data(skill, args, save, body.get("kwargs_override"))
        except Exception as e:
            self._respond(500, str(e))
            return

        if analyses and new_path:
            new_content = Path(new_path).read_text()
            new_content = _reinject_analyses(new_content, analyses)
            Path(new_path).write_text(new_content)

        self._respond(200, "ok")

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

        raise ValueError(f"Unknown skill: {skill}")

    def _run_full(self, skill, args):
        cmd = ["claude", "-p", f"/{skill} {args}"]
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
        if proc.returncode != 0:
            self._respond(500, proc.stderr or "claude CLI failed")
        else:
            self._respond(200, "ok")

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
