"""Cérebro: integração com Ollama, gerenciamento da conversa e tool-calling."""
from __future__ import annotations

import json
from typing import Any, Iterator

import ollama
import requests

from config import MAX_TOOL_ITERATIONS, MODEL_NAME, NUM_CTX, OLLAMA_HOST, SYSTEM_PROMPT
from memory import Memory
from tools import TOOL_SCHEMAS, call_tool


def _to_dict(obj: Any) -> Any:
    """Normaliza respostas do cliente Ollama (pydantic ou dict) para dict puro."""
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return obj


class Brain:
    def __init__(self, memory: Memory, model: str = MODEL_NAME) -> None:
        self.memory = memory
        self.model = model
        self.client = ollama.Client(host=OLLAMA_HOST)

    def health_check(self) -> tuple[bool, str]:
        """Verifica se Ollama está rodando e o modelo configurado existe."""
        try:
            r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=3)
            r.raise_for_status()
            models = r.json().get("models", [])
            names = [m.get("name", "") for m in models]
            if not any(self.model == n or n.startswith(self.model + ":") for n in names):
                available = ", ".join(names) if names else "nenhum"
                return (
                    False,
                    f"modelo '{self.model}' indisponível (instale com: ollama pull {self.model}). Encontrados: {available}",
                )
            return (True, f"online — modelo '{self.model}' pronto")
        except requests.exceptions.ConnectionError:
            return (False, "Ollama offline. Inicie com: ollama serve")
        except requests.exceptions.Timeout:
            return (False, "Ollama não respondeu (timeout)")
        except Exception as e:
            return (False, f"erro: {e}")

    def think(self, user_input: str) -> Iterator[dict[str, Any]]:
        """
        Processa uma interação. Gera eventos no estilo:
          {"type": "tool_call", "name", "args"}
          {"type": "tool_result", "name", "result"}
          {"type": "assistant_start"}
          {"type": "token", "text"}
          {"type": "assistant_end", "full_text"}
          {"type": "error", "message"}
        """
        self.memory.add_message("user", user_input)

        for _ in range(MAX_TOOL_ITERATIONS):
            try:
                response = self.client.chat(
                    model=self.model,
                    messages=self.memory.messages_for_model(SYSTEM_PROMPT),
                    tools=TOOL_SCHEMAS,
                    options={"num_ctx": NUM_CTX},
                )
            except Exception as e:
                yield {"type": "error", "message": f"falha ao consultar Ollama: {e}"}
                return

            data = _to_dict(response)
            msg = data.get("message", {}) or {}
            tool_calls = msg.get("tool_calls") or []

            if not tool_calls:
                content = msg.get("content", "") or ""
                self.memory.add_message("assistant", content)
                yield {"type": "assistant_start"}
                for ch in content:
                    yield {"type": "token", "text": ch}
                yield {"type": "assistant_end", "full_text": content}
                return

            self.memory.add_message(
                "assistant",
                msg.get("content", "") or "",
                tool_calls=tool_calls,
            )

            for tc in tool_calls:
                fn = (tc.get("function") or {}) if isinstance(tc, dict) else {}
                name = fn.get("name", "")
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                yield {"type": "tool_call", "name": name, "args": args}
                result = call_tool(name, args)
                yield {"type": "tool_result", "name": name, "result": result}
                self.memory.add_message("tool", result, name=name)

        warning = "[Limite de iterações de ferramentas atingido.]"
        yield {"type": "assistant_start"}
        for ch in warning:
            yield {"type": "token", "text": ch}
        yield {"type": "assistant_end", "full_text": warning}
