"""Direct BookMyShow HTTP transport for local monitoring.

This module preserves the fetch_json() interface used by main.py.
It does not use ScraperAPI, a proxy, cookies, or browser automation.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests


DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Origin": "https://in.bookmyshow.com",
    "Referer": "https://in.bookmyshow.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
}

# A 403 cooldown is configurable without editing code.
DEFAULT_403_COOLDOWN_SECONDS = 240
DEFAULT_MAX_403_RETRIES = 1


def _retry_after_seconds(response: requests.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None

    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(
                0.0,
                (retry_at - datetime.now(timezone.utc)).total_seconds(),
            )
        except (TypeError, ValueError, OverflowError):
            return None


def fetch_json(
    target_url: str,
    params: dict | None = None,
    timeout: int = 30,
) -> dict:
    """Fetch BMS JSON directly, with a long cooldown after HTTP 403."""

    cooldown = int(
        os.getenv(
            "BMS_403_COOLDOWN_SECONDS",
            str(DEFAULT_403_COOLDOWN_SECONDS),
        )
    )
    max_403_retries = int(
        os.getenv(
            "BMS_403_MAX_RETRIES",
            str(DEFAULT_MAX_403_RETRIES),
        )
    )

    headers = dict(DEFAULT_HEADERS)
    headers["X-Region-Code"] = str((params or {}).get("regionCode", "HYD"))

    # Keep the endpoint parameters supplied by main.py unchanged:
    # dateCode, venueCode, regionCode. Do not substitute `date`.
    with requests.Session() as session:
        session.headers.update(headers)

        network_attempt = 0
        forbidden_retries = 0

        while True:
            try:
                response = session.get(
                    target_url,
                    params=params or {},
                    timeout=timeout,
                )
            except requests.RequestException:
                if network_attempt >= 2:
                    raise
                delay = 3 * (2 ** network_attempt)
                network_attempt += 1
                print(
                    f"Network error. Retrying in {delay} seconds "
                    f"({network_attempt}/2)..."
                )
                time.sleep(delay)
                continue

            print(
                f"BMS direct HTTP status: {response.status_code} "
                f"| URL: {response.url}"
            )

            if response.status_code == 403:
                if forbidden_retries >= max_403_retries:
                    preview = response.text[:250].replace("\n", " ")
                    raise RuntimeError(
                        "BMS returned HTTP 403 after the cooldown retry. "
                        "The request was blocked/challenged. "
                        f"Response preview: {preview!r}"
                    )

                forbidden_retries += 1
                print(
                    "BMS returned HTTP 403. Waiting "
                    f"{cooldown} seconds before one retry..."
                )
                time.sleep(cooldown)
                continue

            if response.status_code == 429:
                delay = _retry_after_seconds(response)
                if delay is None:
                    delay = min(cooldown, 240)
                if network_attempt >= 2:
                    response.raise_for_status()
                network_attempt += 1
                print(
                    f"BMS rate-limited the request. Waiting "
                    f"{delay:.0f} seconds before retry..."
                )
                time.sleep(delay)
                continue

            if 500 <= response.status_code <= 599:
                if network_attempt >= 2:
                    response.raise_for_status()
                delay = 3 * (2 ** network_attempt)
                network_attempt += 1
                print(
                    f"BMS server error. Retrying in {delay} seconds..."
                )
                time.sleep(delay)
                continue

            response.raise_for_status()

            try:
                data = response.json()
            except (ValueError, json.JSONDecodeError) as exc:
                preview = response.text[:300].replace("\n", " ")
                raise RuntimeError(
                    "BMS did not return JSON. It may have returned an "
                    f"HTML challenge page. Response preview: {preview!r}"
                ) from exc

            if not isinstance(data, dict):
                raise RuntimeError(
                    "Unexpected BMS response: expected a JSON object "
                    "at the root."
                )

            return data
