"""ScraperAPI transport for BookMyShow's JSON showtimes endpoint."""

import json
import os

import requests

SCRAPERAPI_ENDPOINT = "https://api.scraperapi.com"


def fetch_json(target_url: str, params: dict | None = None, timeout: int = 90) -> dict:
    """Fetch target_url through ScraperAPI and parse its JSON response."""
    api_key = os.getenv("SCRAPERAPI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing SCRAPERAPI_API_KEY environment variable.")

    prepared_request = requests.Request(
        "GET",
        target_url,
        params=params or {},
    ).prepare()

    if not prepared_request.url:
        raise RuntimeError("Could not construct the BookMyShow request URL.")

    response = requests.get(
        SCRAPERAPI_ENDPOINT,
        params={
            "api_key": api_key,
            "url": prepared_request.url,
        },
        timeout=timeout,
    )

    print(f"ScraperAPI HTTP status: {response.status_code}")
    response.raise_for_status()

    try:
        data = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "ScraperAPI did not return valid JSON from BookMyShow. "
            f"Response begins: {response.text[:300]!r}"
        ) from exc

    if not isinstance(data, dict):
        raise RuntimeError(
            "Unexpected BookMyShow response: expected a JSON object at the root."
        )

    return data
