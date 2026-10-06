"""
Local web agent for the Nes-Dev QA UI. Standard library only.

Security model (this server can start scans, so it must not be driven by random web pages):
* binds to 127.0.0.1 only
* every request must carry a loopback Host header (defeats DNS rebinding)
* the secret session token is only handed to same-origin browser requests (Sec-Fetch-Site), and every API call needs it
* no CORS headers are ever sent, so other sites cannot read responses
"""

import argparse
import hmac
import json
import mimetypes
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import metadata
from urllib.parse import parse_qs, urlparse

from qa_generator import legal
from qa_generator.server.runs import ROOT, RequestError, RunManager

DIST = ROOT / "website" / "dist"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
MAX_BODY = 64 * 1024
SESSION_TOKEN = secrets.token_urlsafe(32)
RUNS = RunManager()

CSP = ("default-src 'self'; img-src 'self' data:; font-src 'self' data:; style-src 'self' 'unsafe-inline'; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


def _version(pkg: str) -> str:
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return "not installed"


class Handler(BaseHTTPRequestHandler):
    server_version = "NesDevQAAgent"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quiet: the run output is what matters
        pass

    # -- plumbing ---------------------------------------------------------
    def _send(self, status: int, body: bytes, ctype: str, extra: dict = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload):
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, err: RequestError):
        self._json(err.status, {"error": err.code, "message": err.message})

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise RequestError(400, "bad_request", "Bad Content-Length.")
        if length > MAX_BODY:
            raise RequestError(413, "too_large", "Request too large.")
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            raise RequestError(415, "bad_content_type", "Send application/json.")
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            raise RequestError(400, "bad_json", "Invalid JSON.")

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        name = host.rsplit(":", 1)[0] if not host.endswith("]") else host
        return name in LOOPBACK_HOSTS

    def _require_token(self):
        if not hmac.compare_digest(self.headers.get("X-QA-Token") or "", SESSION_TOKEN):
            raise RequestError(401, "bad_token", "Missing or invalid session token.")
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{self.headers.get('Host')}":
            raise RequestError(403, "bad_origin", "Cross-origin request refused.")

    # -- routing ----------------------------------------------------------
    def _dispatch(self):
        if not self._host_ok():
            return self._send(403, b"Forbidden host", "text/plain; charset=utf-8")
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/api/"):
                return self._api(parsed)
            if self.command in ("GET", "HEAD"):
                return self._static(parsed.path)
            self._send(405, b"Method not allowed", "text/plain; charset=utf-8")
        except RequestError as err:
            self._error(err)
        except Exception as exc:  # never leak a traceback to the browser
            print(f"[agent] internal error: {exc!r}", file=sys.stderr)
            self._json(500, {"error": "internal", "message": "Internal error. See the agent window."})

    do_GET = do_POST = do_HEAD = _dispatch

    def _api(self, parsed):
        path, method = parsed.path, self.command
        if path == "/api/session" and method == "GET":
            if self.headers.get("Sec-Fetch-Site") not in ("same-origin", "none"):
                raise RequestError(403, "cross_site", "Session is only available to the UI served by this agent.")
            return self._json(200, {"token": SESSION_TOKEN})

        self._require_token()
        if method == "GET" and path == "/api/info":
            return self._json(200, {
                "python": sys.version.split()[0], "playwright": _version("playwright"), "pytest": _version("pytest"),
                "termsAccepted": legal.has_accepted_terms(), "busy": bool(RUNS.current and RUNS.current.status == "running"),
                "historyCount": len(RUNS.history()),
            })
        if method == "GET" and path == "/api/terms":
            return self._json(200, {"terms": legal.read_doc("TERMS_OF_USE.md"), "privacy": legal.read_doc("PRIVACY.md"),
                                    "accepted": legal.has_accepted_terms(), "phrase": legal.AGREE_PHRASE})
        if method == "POST" and path == "/api/terms/accept":
            if self._read_json().get("phrase") != legal.AGREE_PHRASE:
                raise RequestError(400, "wrong_phrase", f'Type "{legal.AGREE_PHRASE}" exactly to accept.')
            legal.accept_terms("web UI")
            return self._json(200, {"accepted": True})
        if method == "GET" and path == "/api/history":
            return self._json(200, {"runs": list(reversed(RUNS.history()))[:50]})
        if method == "POST" and path == "/api/runs":
            run = RUNS.start(self._read_json())
            return self._json(201, run.snapshot())

        parts = path.strip("/").split("/")  # api / runs / <id> [/ results | / cancel]
        if len(parts) >= 3 and parts[1] == "runs":
            run_id = parts[2]
            if len(parts) == 3 and method == "GET":
                after = int((parse_qs(parsed.query).get("after") or ["0"])[0] or 0)
                return self._json(200, RUNS.get(run_id).snapshot(after))
            if len(parts) == 4 and parts[3] == "results" and method == "GET":
                return self._json(200, RUNS.results(run_id))
            if len(parts) == 4 and parts[3] == "cancel" and method == "POST":
                RUNS.cancel(run_id)
                return self._json(200, RUNS.get(run_id).snapshot(10**9))
        raise RequestError(404, "not_found", "Unknown endpoint.")

    def _static(self, url_path: str):
        if not DIST.is_dir():
            body = (b"The UI has not been built yet. Run:  cd website && npm install && npm run build\n"
                    b"Then restart this agent.")
            return self._send(503, body, "text/plain; charset=utf-8")
        rel = "index.html" if url_path in ("", "/") else url_path.lstrip("/")
        target = (DIST / rel).resolve()
        if DIST.resolve() not in target.parents or not target.is_file():
            return self._send(404, b"Not found", "text/plain; charset=utf-8")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Nes-Dev QA local agent (serves the UI and runs scans)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--open", action="store_true", help="Open the UI in your browser")
    args = parser.parse_args(argv)

    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as exc:
        print(f"Could not start on port {args.port}: {exc}")
        return 1
    server.daemon_threads = True
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Nes-Dev QA agent running at {url}")
    print("Only this computer can reach it. Press Ctrl+C to stop.")
    if not DIST.is_dir():
        print("[!] UI not built yet: cd website && npm install && npm run build")
    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        RUNS.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
