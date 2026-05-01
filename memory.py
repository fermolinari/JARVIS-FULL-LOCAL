"""Memória de curto prazo (conversa) e longo prazo (fatos persistidos em JSON)."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from config import MAX_HISTORY, MEMORY_FILE


class Memory:
    """Gerencia histórico da conversa e fatos persistentes."""

    _ALLOWED_KEYS = ("role", "content", "tool_calls", "tool_call_id", "name")

    def __init__(self, max_history: int = MAX_HISTORY) -> None:
        self.history: list[dict[str, Any]] = []
        self.max_history = max_history
        self.facts: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if MEMORY_FILE.exists():
            try:
                self.facts = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self.facts = {}

    def _save(self) -> None:
        MEMORY_FILE.write_text(
            json.dumps(self.facts, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add_message(self, role: str, content: str, **extra: Any) -> None:
        msg: dict[str, Any] = {"role": role, "content": content or ""}
        for key in ("tool_calls", "tool_call_id", "name"):
            if key in extra and extra[key] is not None:
                msg[key] = extra[key]
        self.history.append(msg)
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]

    def messages_for_model(self, system_prompt: str) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        if self.facts:
            summary = "\n".join(f"- {k}: {v['value']}" for k, v in self.facts.items())
            messages.append({
                "role": "system",
                "content": f"Fatos lembrados sobre o usuário:\n{summary}",
            })
        for msg in self.history:
            messages.append({k: v for k, v in msg.items() if k in self._ALLOWED_KEYS})
        return messages

    def remember(self, key: str, value: Any) -> None:
        self.facts[key] = {
            "value": value,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._save()

    def recall(self, key: str) -> Any:
        entry = self.facts.get(key)
        return entry["value"] if entry else None

    def all_facts(self) -> dict[str, Any]:
        return {k: v["value"] for k, v in self.facts.items()}

    def forget(self, key: str) -> bool:
        if key in self.facts:
            del self.facts[key]
            self._save()
            return True
        return False

    def reset_history(self) -> None:
        self.history.clear()
