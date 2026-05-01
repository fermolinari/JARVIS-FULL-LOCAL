"""Módulo de Ação: ferramentas que JARVIS pode invocar via tool-calling."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import psutil

DANGEROUS_KEYWORDS = (
    "rm ", "rm -", "del ", "rmdir", "format ", "shutdown", "reboot",
    "mkfs", ":(){", "dd if=", "> /dev/", "diskpart", "fdisk",
    "taskkill", "kill -9",
)


def _memory():
    from main import MEMORY  # type: ignore[attr-defined]
    return MEMORY


def _notes():
    from main import NOTES  # type: ignore[attr-defined]
    return NOTES


# --- Sistema -----------------------------------------------------------------

def get_system_status() -> dict[str, Any]:
    cpu_percent = psutil.cpu_percent(interval=0.4)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    boot_time = datetime.fromtimestamp(psutil.boot_time())
    uptime = datetime.now() - boot_time
    return {
        "cpu_percent": cpu_percent,
        "cpu_count": psutil.cpu_count(),
        "ram_used_gb": round(mem.used / (1024 ** 3), 2),
        "ram_total_gb": round(mem.total / (1024 ** 3), 2),
        "ram_percent": mem.percent,
        "disk_used_gb": round(disk.used / (1024 ** 3), 2),
        "disk_total_gb": round(disk.total / (1024 ** 3), 2),
        "disk_percent": disk.percent,
        "uptime": str(uptime).split(".")[0],
        "platform": platform.system(),
        "platform_release": platform.release(),
    }


def list_processes(top_n: int = 10) -> list[dict[str, Any]]:
    procs: list[dict[str, Any]] = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            procs.append(p.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    procs.sort(key=lambda x: x.get("cpu_percent") or 0, reverse=True)
    return procs[:max(1, min(top_n, 50))]


def execute_shell(command: str, timeout: int = 30) -> dict[str, Any]:
    is_dangerous = any(kw in command.lower() for kw in DANGEROUS_KEYWORDS)
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=timeout,
        )
        return {
            "command": command,
            "exit_code": result.returncode,
            "stdout": (result.stdout or "")[-4000:],
            "stderr": (result.stderr or "")[-2000:],
            "dangerous": is_dangerous,
        }
    except subprocess.TimeoutExpired:
        return {"command": command, "error": f"timeout após {timeout}s.", "dangerous": is_dangerous}
    except Exception as e:
        return {"command": command, "error": str(e), "dangerous": is_dangerous}


def read_file(path: str, max_chars: int = 8000) -> dict[str, Any]:
    p = Path(path).expanduser()
    if not p.exists():
        return {"path": str(p), "error": "arquivo não encontrado."}
    if not p.is_file():
        return {"path": str(p), "error": "caminho não é um arquivo."}
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        return {
            "path": str(p),
            "size_bytes": p.stat().st_size,
            "content": content[:max_chars],
            "truncated": len(content) > max_chars,
        }
    except Exception as e:
        return {"path": str(p), "error": str(e)}


def list_directory(path: str = ".") -> dict[str, Any]:
    p = Path(path).expanduser()
    if not p.exists():
        return {"path": str(p), "error": "caminho não existe."}
    if not p.is_dir():
        return {"path": str(p), "error": "caminho não é um diretório."}
    try:
        entries = []
        for child in sorted(p.iterdir()):
            try:
                entries.append({
                    "name": child.name,
                    "type": "dir" if child.is_dir() else "file",
                    "size": child.stat().st_size if child.is_file() else None,
                })
            except OSError:
                continue
        return {"path": str(p.resolve()), "count": len(entries), "entries": entries[:200]}
    except Exception as e:
        return {"path": str(p), "error": str(e)}


def get_current_time() -> dict[str, str]:
    now = datetime.now()
    weekdays = ["segunda-feira","terça-feira","quarta-feira","quinta-feira","sexta-feira","sábado","domingo"]
    return {
        "iso": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M"),
        "weekday": weekdays[now.weekday()],
    }


# --- Memória ----------------------------------------------------------------

def remember(key: str, value: str) -> dict[str, Any]:
    _memory().remember(key, value)
    return {"ok": True, "key": key, "value": value}


def recall(key: str) -> dict[str, Any]:
    value = _memory().recall(key)
    if value is None:
        return {"found": False, "key": key}
    return {"found": True, "key": key, "value": value}


def list_facts() -> dict[str, Any]:
    return {"facts": _memory().all_facts()}


# --- Notas e agenda ---------------------------------------------------------

def add_note(text: str, title: str = "") -> dict[str, Any]:
    return _notes().add_note(text, title)


def list_notes(limit: int = 20) -> dict[str, Any]:
    return {"notes": _notes().list_notes(limit)}


def search_notes(query: str) -> dict[str, Any]:
    return {"matches": _notes().search_notes(query)}


def delete_note(note_id: str) -> dict[str, Any]:
    return {"ok": _notes().delete_note(note_id), "id": note_id}


def add_event(title: str, when: str, description: str = "") -> dict[str, Any]:
    return _notes().add_event(title, when, description)


def list_events(upcoming_only: bool = False) -> dict[str, Any]:
    return {"events": _notes().list_events(upcoming_only)}


def delete_event(event_id: str) -> dict[str, Any]:
    return {"ok": _notes().delete_event(event_id), "id": event_id}


# --- Apps, janelas, automação -----------------------------------------------

# Atalhos comuns no Windows. JARVIS tenta resolver pelo nome também.
WINDOWS_APP_ALIASES = {
    "bloco de notas": "notepad",
    "notepad": "notepad",
    "calculadora": "calc",
    "calc": "calc",
    "explorador": "explorer",
    "explorer": "explorer",
    "navegador": "msedge",
    "edge": "msedge",
    "chrome": "chrome",
    "firefox": "firefox",
    "terminal": "wt",
    "powershell": "powershell",
    "cmd": "cmd",
    "spotify": "spotify",
    "vscode": "code",
    "code": "code",
    "vs code": "code",
    "paint": "mspaint",
    "configurações": "ms-settings:",
    "settings": "ms-settings:",
}


def open_app(name: str) -> dict[str, Any]:
    """Abre um aplicativo pelo nome (alias) ou caminho."""
    key = name.strip().lower()
    target = WINDOWS_APP_ALIASES.get(key, name)
    is_windows = platform.system() == "Windows"
    try:
        if is_windows:
            if target.startswith("ms-settings:") or target.startswith("http"):
                os.startfile(target)
            elif shutil.which(target):
                subprocess.Popen([target], shell=False)
            else:
                # Fallback: deixa o shell encontrar (apps na PATH ou no menu Iniciar)
                subprocess.Popen(["cmd", "/c", "start", "", target], shell=False)
        else:
            subprocess.Popen([target])
        return {"ok": True, "opened": target}
    except Exception as e:
        return {"ok": False, "error": str(e), "target": target}


def list_windows() -> dict[str, Any]:
    """Lista janelas visíveis (título não-vazio)."""
    try:
        import pygetwindow as gw
    except ImportError:
        return {"error": "pygetwindow indisponível."}
    titles = [t for t in gw.getAllTitles() if t and t.strip()]
    return {"count": len(titles), "windows": titles[:60]}


def focus_window(title: str) -> dict[str, Any]:
    """Foca a primeira janela cujo título contém `title` (case-insensitive)."""
    try:
        import pygetwindow as gw
    except ImportError:
        return {"error": "pygetwindow indisponível."}
    matches = [w for w in gw.getAllWindows() if title.lower() in (w.title or "").lower() and w.title.strip()]
    if not matches:
        return {"ok": False, "error": f"nenhuma janela com '{title}' encontrada."}
    win = matches[0]
    try:
        if win.isMinimized:
            win.restore()
        win.activate()
        return {"ok": True, "title": win.title}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def close_window(title: str) -> dict[str, Any]:
    try:
        import pygetwindow as gw
    except ImportError:
        return {"error": "pygetwindow indisponível."}
    matches = [w for w in gw.getAllWindows() if title.lower() in (w.title or "").lower() and w.title.strip()]
    if not matches:
        return {"ok": False, "error": f"nenhuma janela com '{title}' encontrada."}
    try:
        matches[0].close()
        return {"ok": True, "title": matches[0].title}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_active_window() -> dict[str, Any]:
    try:
        import pygetwindow as gw
    except ImportError:
        return {"error": "pygetwindow indisponível."}
    try:
        win = gw.getActiveWindow()
        return {"title": win.title if win else None}
    except Exception as e:
        return {"error": str(e)}


def type_text(text: str, interval: float = 0.02) -> dict[str, Any]:
    """Digita texto na janela ativa."""
    try:
        import pyautogui
    except ImportError:
        return {"error": "pyautogui indisponível."}
    try:
        pyautogui.write(text, interval=interval)
        return {"ok": True, "chars": len(text)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def press_key(key: str) -> dict[str, Any]:
    """Pressiona uma tecla (ex: 'enter', 'esc', 'win', 'space')."""
    try:
        import pyautogui
    except ImportError:
        return {"error": "pyautogui indisponível."}
    try:
        pyautogui.press(key)
        return {"ok": True, "key": key}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def hotkey(*keys: str) -> dict[str, Any]:
    """Pressiona combinação de teclas (ex: hotkey('ctrl','c'))."""
    try:
        import pyautogui
    except ImportError:
        return {"error": "pyautogui indisponível."}
    try:
        pyautogui.hotkey(*keys)
        return {"ok": True, "keys": list(keys)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def clipboard_get() -> dict[str, Any]:
    try:
        import pyperclip
        return {"text": pyperclip.paste()}
    except Exception as e:
        return {"error": str(e)}


def clipboard_set(text: str) -> dict[str, Any]:
    try:
        import pyperclip
        pyperclip.copy(text)
        return {"ok": True, "chars": len(text)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def screenshot(path: str = "") -> dict[str, Any]:
    """Captura a tela. Salva em `path` (ou em ./screenshot_<ts>.png)."""
    try:
        import pyautogui
    except ImportError:
        return {"error": "pyautogui indisponível."}
    if not path:
        path = f"screenshot_{int(time.time())}.png"
    try:
        img = pyautogui.screenshot()
        img.save(path)
        return {"ok": True, "path": str(Path(path).resolve())}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --- Schemas para tool-calling ----------------------------------------------

def _fn(name: str, desc: str, props: dict | None = None, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": props or {},
                "required": required or [],
            },
        },
    }


TOOL_SCHEMAS: list[dict[str, Any]] = [
    _fn("get_system_status", "Status do sistema: CPU, RAM, disco, uptime."),
    _fn("list_processes", "Processos mais ativos por CPU.",
        {"top_n": {"type": "integer", "default": 10}}),
    _fn("execute_shell", "Executa um comando shell. Comandos destrutivos ficam marcados.",
        {"command": {"type": "string"}, "timeout": {"type": "integer", "default": 30}}, ["command"]),
    _fn("read_file", "Lê o conteúdo (texto) de um arquivo.",
        {"path": {"type": "string"}}, ["path"]),
    _fn("list_directory", "Lista o conteúdo de um diretório.",
        {"path": {"type": "string", "default": "."}}),
    _fn("get_current_time", "Data e hora atuais."),
    _fn("remember", "Armazena um fato persistente sobre o usuário.",
        {"key": {"type": "string"}, "value": {"type": "string"}}, ["key", "value"]),
    _fn("recall", "Recupera um fato pela chave.",
        {"key": {"type": "string"}}, ["key"]),
    _fn("list_facts", "Lista todos os fatos lembrados."),

    _fn("add_note", "Cria uma nota livre na agenda do usuário.",
        {"text": {"type": "string"}, "title": {"type": "string"}}, ["text"]),
    _fn("list_notes", "Lista as notas mais recentes.",
        {"limit": {"type": "integer", "default": 20}}),
    _fn("search_notes", "Busca notas por termo.",
        {"query": {"type": "string"}}, ["query"]),
    _fn("delete_note", "Apaga uma nota pelo id.",
        {"note_id": {"type": "string"}}, ["note_id"]),
    _fn("add_event", "Adiciona um compromisso à agenda. `when` em ISO (YYYY-MM-DDTHH:MM).",
        {"title": {"type": "string"}, "when": {"type": "string"}, "description": {"type": "string"}}, ["title", "when"]),
    _fn("list_events", "Lista compromissos.",
        {"upcoming_only": {"type": "boolean", "default": False}}),
    _fn("delete_event", "Apaga um compromisso pelo id.",
        {"event_id": {"type": "string"}}, ["event_id"]),

    _fn("open_app", "Abre um aplicativo pelo nome (notepad, calc, chrome, spotify, code, etc.) ou caminho.",
        {"name": {"type": "string"}}, ["name"]),
    _fn("list_windows", "Lista janelas abertas (títulos)."),
    _fn("focus_window", "Foca a primeira janela cujo título contenha o termo.",
        {"title": {"type": "string"}}, ["title"]),
    _fn("close_window", "Fecha a primeira janela cujo título contenha o termo.",
        {"title": {"type": "string"}}, ["title"]),
    _fn("get_active_window", "Retorna o título da janela em foco."),

    _fn("type_text", "Digita texto na janela ativa.",
        {"text": {"type": "string"}, "interval": {"type": "number", "default": 0.02}}, ["text"]),
    _fn("press_key", "Pressiona uma tecla (enter, esc, space, win, f5, ...).",
        {"key": {"type": "string"}}, ["key"]),
    _fn("hotkey", "Combinação de teclas. Passe a lista em `keys`, ex: ['ctrl','c'].",
        {"keys": {"type": "array", "items": {"type": "string"}}}, ["keys"]),
    _fn("clipboard_get", "Lê o texto atual do clipboard."),
    _fn("clipboard_set", "Define o texto do clipboard.",
        {"text": {"type": "string"}}, ["text"]),
    _fn("screenshot", "Captura a tela atual.",
        {"path": {"type": "string", "default": ""}}),
]


def _hotkey_dispatch(keys=None, **rest):
    if keys is None:
        keys = list(rest.values())
    return hotkey(*keys)


TOOL_REGISTRY: dict[str, Callable[..., Any]] = {
    "get_system_status": get_system_status,
    "list_processes": list_processes,
    "execute_shell": execute_shell,
    "read_file": read_file,
    "list_directory": list_directory,
    "get_current_time": get_current_time,
    "remember": remember,
    "recall": recall,
    "list_facts": list_facts,
    "add_note": add_note,
    "list_notes": list_notes,
    "search_notes": search_notes,
    "delete_note": delete_note,
    "add_event": add_event,
    "list_events": list_events,
    "delete_event": delete_event,
    "open_app": open_app,
    "list_windows": list_windows,
    "focus_window": focus_window,
    "close_window": close_window,
    "get_active_window": get_active_window,
    "type_text": type_text,
    "press_key": press_key,
    "hotkey": _hotkey_dispatch,
    "clipboard_get": clipboard_get,
    "clipboard_set": clipboard_set,
    "screenshot": screenshot,
}


def call_tool(name: str, args: dict[str, Any]) -> str:
    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        return json.dumps({"error": f"ferramenta desconhecida: {name}"}, ensure_ascii=False)
    try:
        result = fn(**(args or {}))
    except TypeError as e:
        return json.dumps({"error": f"argumentos inválidos: {e}"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False, default=str)
