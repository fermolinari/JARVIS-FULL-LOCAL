"""
JARVIS — janela "desktop" via Edge em modo app + servidor HTTP local com SSE.

Arquitetura:
  - Servidor HTTP stdlib (ThreadingHTTPServer) serve frontend/ e expõe /api/*
  - SSE (text/event-stream) empurra eventos do backend pro frontend
  - JS chama /api/send_message via fetch
  - Edge é aberto com --app=URL pra parecer um app desktop (sem barra/abas)
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from audio_listener import ClapListener
from brain import Brain
from config import (
    ASSISTANT_NAME,
    CLAP_ENABLED,
    FRONTEND_DIR,
    USER_TITLE,
    WINDOW_HEIGHT,
    WINDOW_WIDTH,
)
from memory import Memory
from notes import NotesStore

MEMORY = Memory()
NOTES = NotesStore()
BRAIN = Brain(MEMORY)


def _greeting() -> str:
    h = datetime.now().hour
    if h < 12:
        period = "Bom dia"
    elif h < 18:
        period = "Boa tarde"
    else:
        period = "Boa noite"
    return f"{period}, {USER_TITLE}. Em que posso lhe ser útil?"


# --- Bus de eventos pra SSE -----------------------------------------------

class EventBus:
    """Distribui eventos pra todos os clientes SSE conectados."""

    def __init__(self) -> None:
        self._clients: list[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=200)
        with self._lock:
            self._clients.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass


BUS = EventBus()


def process_turn(text: str) -> None:
    """Roda em background; despeja eventos no bus."""
    try:
        for ev in BRAIN.think(text):
            BUS.publish(ev)
    except Exception as e:
        BUS.publish({"type": "error", "message": f"falha: {e}"})


# --- Handler HTTP --------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "JARVIS/1.0"

    # Silencia logs ruidosos do http.server
    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_text(self, code: int, body: str, content_type: str = "text/plain; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, code: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False)
        self._send_text(code, body, "application/json; charset=utf-8")

    def _serve_static(self, rel: str) -> None:
        # Resolve seguro contra path traversal
        rel = rel.lstrip("/")
        if not rel or rel.endswith("/"):
            rel = (rel + "index.html").lstrip("/")
        target = (FRONTEND_DIR / rel).resolve()
        try:
            target.relative_to(FRONTEND_DIR.resolve())
        except ValueError:
            self._send_text(403, "forbidden")
            return
        if not target.is_file():
            self._send_text(404, "not found")
            return
        ext = target.suffix.lower()
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".css":  "text/css; charset=utf-8",
            ".js":   "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".png":  "image/png",
            ".jpg":  "image/jpeg",
            ".svg":  "image/svg+xml",
            ".ico":  "image/x-icon",
        }.get(ext, "application/octet-stream")
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _serve_sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        q = BUS.subscribe()
        try:
            # Hello inicial pra garantir abertura imediata
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    ev = q.get(timeout=15)
                except queue.Empty:
                    # heartbeat de keep-alive
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                payload = "data: " + json.dumps(ev, ensure_ascii=False) + "\n\n"
                self.wfile.write(payload.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            BUS.unsubscribe(q)

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path == "/api/events":
            self._serve_sse()
            return
        if url.path == "/api/health":
            ok, detail = BRAIN.health_check()
            self._send_json(200, {"ok": ok, "message": detail})
            return
        # Estáticos
        rel = url.path if url.path != "/" else "/index.html"
        self._serve_static(rel)

    def do_POST(self) -> None:
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except json.JSONDecodeError:
            payload = {}

        if url.path == "/api/send_message":
            text = (payload.get("text") or "").strip()
            if not text:
                self._send_json(400, {"ok": False, "error": "vazio"})
                return
            threading.Thread(target=process_turn, args=(text,), daemon=True).start()
            self._send_json(200, {"ok": True})
            return

        if url.path == "/api/greet":
            msg = _greeting()
            BUS.publish({"type": "wake", "message": msg})
            self._send_json(200, {"ok": True, "message": msg})
            return

        self._send_text(404, "not found")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _open_in_app_window(url: str) -> bool:
    """Tenta abrir no Edge/Chrome em modo --app (sem chrome do navegador)."""
    candidates: list[list[str]] = []

    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        edge_paths = [
            rf"{program_files}\Microsoft\Edge\Application\msedge.exe",
            rf"{program_files_x86}\Microsoft\Edge\Application\msedge.exe",
        ]
        chrome_paths = [
            rf"{program_files}\Google\Chrome\Application\chrome.exe",
            rf"{program_files_x86}\Google\Chrome\Application\chrome.exe",
            rf"{local}\Google\Chrome\Application\chrome.exe",
        ]
        for p in edge_paths + chrome_paths:
            if os.path.isfile(p):
                candidates.append([p, f"--app={url}", f"--window-size={WINDOW_WIDTH},{WINDOW_HEIGHT}"])
                break
    # Fallback genérico
    for browser in ("msedge", "chrome", "google-chrome", "chromium"):
        which = shutil.which(browser)
        if which:
            candidates.append([which, f"--app={url}", f"--window-size={WINDOW_WIDTH},{WINDOW_HEIGHT}"])
            break

    for cmd in candidates:
        try:
            subprocess.Popen(cmd)
            return True
        except Exception:
            continue
    return False


def main() -> int:
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True

    server_thread = threading.Thread(target=server.serve_forever, daemon=True, name="HttpServer")
    server_thread.start()

    url = f"http://127.0.0.1:{port}/"
    print(f"[{ASSISTANT_NAME}] servidor iniciado em {url}")

    clap_listener: ClapListener | None = None
    if CLAP_ENABLED:
        clap_listener = ClapListener(
            on_double_clap=lambda: BUS.publish({"type": "wake", "message": _greeting()})
        )
        if clap_listener.available():
            clap_listener.start()
            print(f"[{ASSISTANT_NAME}] clap detector ativo (bata 2 palmas pra cumprimentar).")
        else:
            print(f"[{ASSISTANT_NAME}] sounddevice indisponível — clap detector desativado.")

    if not _open_in_app_window(url):
        # Último recurso: abre no navegador padrão
        import webbrowser
        webbrowser.open(url)
        print(f"[{ASSISTANT_NAME}] abriu no navegador padrão (Edge/Chrome em modo app indisponível).")

    print(f"[{ASSISTANT_NAME}] online. Ctrl+C pra encerrar.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n[{ASSISTANT_NAME}] encerrando...")
    finally:
        if clap_listener:
            clap_listener.stop()
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
