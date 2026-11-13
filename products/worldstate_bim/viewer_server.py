"""Local-only preview and controlled parameter editing for assisted BIM drafts."""
from __future__ import annotations

import argparse
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .assisted import revise_length, write_model
from .parametric_ir import digest, validate_ir


class ViewerServer(ThreadingHTTPServer):
    """Serve one explicitly chosen draft without accessing unrelated files."""

    def __init__(self, port: int, model_dir: Path, evidence_root: Path, workspace: Path):
        super().__init__(("127.0.0.1", port), Handler)
        self.model_dir = model_dir.resolve(strict=True)
        self.evidence_root = evidence_root.resolve(strict=True)
        self.workspace = workspace.resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.model = json.loads((self.model_dir / "model.json").read_text())
        validate_ir(self.model)
        if not (self.model_dir / "model.ifc").is_file():
            raise ValueError("model.ifc is missing")
        self.token = secrets.token_urlsafe(24)
        self.lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    server: ViewerServer

    def log_message(self, format: str, *args: object) -> None:
        """Do not log local evidence paths or request bodies."""

    def _send(self, code: int, data: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/":
            html = Path(__file__).with_name("viewer.html").read_text().replace("__WS_TOKEN__", self.server.token)
            self._send(200, html.encode(), "text/html; charset=utf-8")
        elif path == "/api/model":
            self._send(200, json.dumps(self.server.model, ensure_ascii=False, allow_nan=False).encode(), "application/json")
        elif path == "/api/photo":
            source = next(x for x in self.server.model["evidence"] if x["id"] == "photo-1")
            name = source["name"]
            photo = self.server.evidence_root / name
            if Path(name).name != name or not photo.is_file() or digest(photo) != source["sha256"]:
                self._send(404, b"source image unavailable or hash mismatch", "text/plain")
                return
            self._send(200, photo.read_bytes(), "image/png" if photo.suffix.lower() == ".png" else "image/jpeg")
        elif path == "/api/model.ifc":
            self._send(200, (self.server.model_dir / "model.ifc").read_bytes(), "application/octet-stream")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/api/revise":
            self._send(404, b"not found", "text/plain")
            return
        expected_origin = f"http://127.0.0.1:{self.server.server_port}"
        if self.headers.get("Origin") != expected_origin or not secrets.compare_digest(
                self.headers.get("X-WorldState-Token", ""), self.server.token):
            self._send(403, b"local origin and session token required", "text/plain")
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > 8192:
                raise ValueError("invalid request size")
            body = json.loads(self.rfile.read(size))
            with self.server.lock:
                revised, diff = revise_length(self.server.model, body["wall_id"], body["length_m"],
                                              body["reason"], operator="user")
                target = self.server.workspace / f"revision-{revised['revision']:03}"
                write_model(revised, self.server.evidence_root, target)
                (target / "diff.json").write_text(json.dumps(diff, indent=2, ensure_ascii=False) + "\n")
                self.server.model, self.server.model_dir = revised, target
            self._send(200, json.dumps({"model": revised, "diff": diff}, ensure_ascii=False).encode(), "application/json")
        except (KeyError, TypeError, ValueError, FileExistsError, json.JSONDecodeError) as exc:
            self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True, help="Local revision output directory")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ViewerServer(args.port, args.model_dir, args.evidence_root, args.workspace)
    print(f"Local preview: http://127.0.0.1:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
