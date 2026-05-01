"""Notas livres + agenda de compromissos persistidas em notes.json."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from config import NOTES_FILE


class NotesStore:
    def __init__(self) -> None:
        self.data: dict[str, list[dict[str, Any]]] = {"notes": [], "events": []}
        self._load()

    def _load(self) -> None:
        if NOTES_FILE.exists():
            try:
                self.data = json.loads(NOTES_FILE.read_text(encoding="utf-8"))
                self.data.setdefault("notes", [])
                self.data.setdefault("events", [])
            except (json.JSONDecodeError, OSError):
                self.data = {"notes": [], "events": []}

    def _save(self) -> None:
        NOTES_FILE.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # --- Notas ---

    def add_note(self, text: str, title: str = "") -> dict[str, Any]:
        note = {
            "id": uuid.uuid4().hex[:8],
            "title": title or text[:40],
            "text": text,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.data["notes"].append(note)
        self._save()
        return note

    def list_notes(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self.data["notes"][-limit:])

    def search_notes(self, query: str) -> list[dict[str, Any]]:
        q = query.lower()
        return [n for n in self.data["notes"] if q in n["text"].lower() or q in n["title"].lower()]

    def delete_note(self, note_id: str) -> bool:
        before = len(self.data["notes"])
        self.data["notes"] = [n for n in self.data["notes"] if n["id"] != note_id]
        if len(self.data["notes"]) < before:
            self._save()
            return True
        return False

    # --- Agenda ---

    def add_event(self, title: str, when: str, description: str = "") -> dict[str, Any]:
        event = {
            "id": uuid.uuid4().hex[:8],
            "title": title,
            "when": when,
            "description": description,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.data["events"].append(event)
        self.data["events"].sort(key=lambda e: e.get("when", ""))
        self._save()
        return event

    def list_events(self, upcoming_only: bool = False) -> list[dict[str, Any]]:
        events = list(self.data["events"])
        if upcoming_only:
            now_iso = datetime.now().isoformat(timespec="seconds")
            events = [e for e in events if e.get("when", "") >= now_iso]
        return events

    def delete_event(self, event_id: str) -> bool:
        before = len(self.data["events"])
        self.data["events"] = [e for e in self.data["events"] if e["id"] != event_id]
        if len(self.data["events"]) < before:
            self._save()
            return True
        return False
