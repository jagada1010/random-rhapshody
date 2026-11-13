
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
        "theatre_name",
        "format_label",
        "movie",
        "language",
        "dimension",
        "event_code",
        "session_id",
        "date",
        "time",
        "screen",
        "attributes",
        "venue_code",
        "target_id",
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
            loaded = json.loads(
                self.path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Cannot read monitor state {self.path}: {exc}"
            ) from exc

        if (
            not isinstance(loaded, dict)
            or loaded.get("version") != 1
            or not isinstance(loaded.get("profiles"), dict)
        ):
            raise RuntimeError(
                f"Monitor state {self.path} has an unsupported/corrupt "
                "structure; refusing to overwrite it."
            )

        return loaded

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        fd, temp_name = tempfile.mkstemp(
            prefix="state-",
            suffix=".tmp",
            dir=str(self.path.parent),
        )

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    self.data,
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
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
        return "|".join((
            str(show.get("target_id", "")),
            str(show.get("date", "")),
            str(show.get("session_id", "")),
        ))

    def _get_or_create_profile(self, profile_key: str) -> dict:
        return self.data["profiles"].setdefault(
            profile_key,
            {
                "initialized": False,
                "archive": {},
                "pending_changes": [],
                "last_sleep_email_at": None,
                "last_successful_run": None,
            },
        )

    def record_partial_snapshot(
        self,
        profile_key: str,
        shows: list,
        successful_scopes: set,
        now: datetime,
    ) -> dict:
        """
        Record a partial or complete snapshot.

        successful_scopes contains (venue_code, target_date) tuples.

        Only records belonging to successfully validated scopes can be
        marked absent. Failed scopes retain their previous state unchanged.
        """

        if not successful_scopes:
            raise ValueError(
                "Cannot record a snapshot without successful venue/date scopes."
            )

        normalized_scopes = {
            (str(venue).upper(), str(date))
            for venue, date in successful_scopes
        }

        now_text = now.isoformat(timespec="seconds")

        profile = self._get_or_create_profile(profile_key)
        archive = profile["archive"]
        pending = profile["pending_changes"]

        first_snapshot = not profile["initialized"]
        current_keys = set()

        # Add new sessions and update existing sessions.
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
                    pending.append({
                        "type": "new",
                        "timestamp": now_text,
                        "show": deepcopy(show),
                    })

                continue

            was_not_listed = (
                existing.get("status") != "currently_listed"
            )

            if was_not_listed:
                existing["last_change"] = now_text

                if not first_snapshot:
                    pending.append({
                        "type": "reappeared",
                        "timestamp": now_text,
                        "show": deepcopy(show),
                    })

            changed_fields = [
                field
                for field in self.TRACKED_FIELDS
                if str(existing.get(field, "")) != str(show.get(field, ""))
            ]

            if changed_fields:
                existing["last_change"] = now_text

                if not first_snapshot:
                    pending.append({
                        "type": "updated",
                        "timestamp": now_text,
                        "show": deepcopy(show),
                        "changed_fields": changed_fields,
                    })

            # Refresh tracked fields while retaining historical metadata.
            for field in self.TRACKED_FIELDS:
                if field in show:
                    existing[field] = show[field]

            existing["last_seen"] = now_text
            existing["status"] = "currently_listed"

        # Mark sessions absent ONLY inside successfully fetched scopes.
        # A failed venue/date must never cause its old sessions to disappear.
        for key, record in archive.items():
            scope = (
                str(record.get("venue_code", "")).upper(),
                str(record.get("date", "")),
            )

            if scope not in normalized_scopes:
                continue

            if key in current_keys:
                continue

            if record.get("status") != "not_currently_listed":
                record["status"] = "not_currently_listed"
                record["last_change"] = now_text

            # Disappearance alone deliberately does not create an email alert.

        profile["initialized"] = True
        profile["last_successful_run"] = now_text

        self._save()

        return self.get_profile(profile_key)

    def record_successful_snapshot(
        self,
        profile_key: str,
        shows: list,
        now: datetime,
    ) -> dict:
        """
        Backward-compatible wrapper for callers recording a complete
        snapshot containing at least one show.

        The monitor itself should use record_partial_snapshot().
        """
        scopes = {
            (
                str(show.get("venue_code", "")).upper(),
                str(show.get("date", "")),
            )
            for show in shows
        }

        if not scopes:
            raise ValueError(
                "Use record_partial_snapshot() with successful_scopes "
                "when a successful snapshot contains zero matching shows."
            )

        return self.record_partial_snapshot(
            profile_key,
            shows,
            scopes,
            now,
        )

    def get_profile(self, profile_key: str) -> dict:
        profile = self.data["profiles"][profile_key]

        return {
            "archive": list(profile["archive"].values()),
            "pending_changes": deepcopy(
                profile["pending_changes"]
            ),
            "last_sleep_email_at": profile.get(
                "last_sleep_email_at"
            ),
            "last_successful_run": profile.get(
                "last_successful_run"
            ),
        }

    def clear_pending_changes(self, profile_key: str) -> None:
        profile = self.data["profiles"][profile_key]

        if profile["pending_changes"]:
            profile["pending_changes"] = []
            self._save()
