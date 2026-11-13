"""Persistent, append-only session archive for the BookMyShow monitor."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile


class MonitorState:
    TRACKED_FIELDS = (
        "theatre_name", "format_label", "movie", "language", "dimension",
        "event_code", "session_id", "date", "time", "screen", "attributes",
        "venue_code", "target_id",
    )

    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = self._load()

    @staticmethod
    def _empty_state() -> dict:
        return {"version": 1, "profiles": {}}

    def _load(self) -> dict:
        if not self.path.exists():
            return self._empty_state()
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Cannot read monitor state {self.path}: {exc}") from exc
        if not isinstance(loaded, dict) or loaded.get("version") != 1 or not isinstance(loaded.get("profiles"), dict):
            raise RuntimeError(f"Monitor state {self.path} has an unsupported/corrupt structure; refusing to overwrite it.")
        return loaded

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix="state-", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temp_name, self.path)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise

    @staticmethod
    def _session_key(show: dict) -> str:
        return "|".join((str(show.get("target_id", "")), str(show.get("date", "")), str(show.get("session_id", ""))))

    def record_successful_snapshot(self, profile_key: str, shows: list, now: datetime) -> dict:
        """Record only after caller has validated every requested API response."""
        now_text = now.isoformat(timespec="seconds")
        profiles = self.data["profiles"]
        profile = profiles.setdefault(profile_key, {
            "initialized": False,
            "archive": {},
            "pending_changes": [],
            "last_sleep_email_at": None,
            "last_successful_run": None,
        })
        archive = profile["archive"]
        first_snapshot = not profile["initialized"]
        current_keys = set()
        pending = profile["pending_changes"]

        for show in shows:
            key = self._session_key(show)
            current_keys.add(key)
            existing = archive.get(key)
            if existing is None:
                record = deepcopy(show)
                record.update({
                    "first_seen": now_text,
                    "last_seen": now_text,
                    "last_change": now_text,
                    "status": "currently_listed",
                })
                archive[key] = record
                if not first_snapshot:
                    pending.append({"type": "new", "timestamp": now_text, "show": deepcopy(show)})
                continue

            was_not_listed = existing.get("status") != "currently_listed"
            if was_not_listed:
                existing["last_change"] = now_text
                if not first_snapshot:
                    pending.append({"type": "reappeared", "timestamp": now_text, "show": deepcopy(show)})
            changed_fields = [field for field in self.TRACKED_FIELDS if str(existing.get(field, "")) != str(show.get(field, ""))]
            if changed_fields:
                existing["last_change"] = now_text
            if changed_fields and not first_snapshot:
                pending.append({
                    "type": "updated", "timestamp": now_text,
                    "show": deepcopy(show), "changed_fields": changed_fields,
                })
            # Keep the full record while refreshing the current source fields.
            for field in self.TRACKED_FIELDS:
                if field in show:
                    existing[field] = show[field]
            existing["last_seen"] = now_text
            existing["status"] = "currently_listed"

        # Only a fully successful snapshot can mark previously known shows absent.
        for key, record in archive.items():
            if key not in current_keys and record.get("status") != "not_currently_listed":
                record["status"] = "not_currently_listed"
                record["last_change"] = now_text

        profile["initialized"] = True
        profile["last_successful_run"] = now_text
        self._save()
        return self.get_profile(profile_key)

    def get_profile(self, profile_key: str) -> dict:
        profile = self.data["profiles"][profile_key]
        return {
            "archive": list(profile["archive"].values()),
            "pending_changes": deepcopy(profile["pending_changes"]),
            "last_sleep_email_at": profile.get("last_sleep_email_at"),
        }

    def mark_sleep_alert_sent(self, profile_key: str, now: datetime) -> None:
        profile = self.data["profiles"][profile_key]
        profile["last_sleep_email_at"] = now.isoformat(timespec="seconds")
        profile["pending_changes"] = []
        self._save()

    def clear_pending_changes(self, profile_key: str) -> None:
        profile = self.data["profiles"][profile_key]
        if profile["pending_changes"]:
            profile["pending_changes"] = []
            self._save()
