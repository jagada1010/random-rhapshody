
import json
import os
import time
import requests
from datetime import datetime, timezone

# ============================================================
# CONFIGURATION
# ============================================================

API_URL = "https://in.bookmyshow.com/api/v3/mobile/showtimes/byvenue"

REGION_CODE = "HYD"
REGION_SLUG = "hyderabad"

# Use the same venue/date combination as your existing config.
VENUE_CODE = os.getenv("BMS_TEST_VENUE", "ALUC")
TARGET_DATE = os.getenv("BMS_TEST_DATE", "20261116")

TIMEOUT = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Origin": "https://in.bookmyshow.com",
    "Referer": "https://in.bookmyshow.com/",
    "X-Region-Code": REGION_CODE,
    "X-Region-Slug": REGION_SLUG,
}


def print_section(title):
    print("\n" + "=" * 65)
    print(title)
    print("=" * 65)


def get_public_ip():
    print_section("1. GITHUB RUNNER PUBLIC IP")

    try:
        response = requests.get(
            "https://api.ipify.org?format=json",
            timeout=15
        )
        response.raise_for_status()

        ip = response.json().get("ip")
        print(f"Public IP: {ip}")
        return ip

    except requests.RequestException as exc:
        print(f"Could not determine public IP: {exc}")
        return None


def test_bms():
    print_section("2. DIRECT BOOKMYSHOW REQUEST")

    params = {
        "regionCode": REGION_CODE,
        "regionSlug": REGION_SLUG,
        "venueCode": VENUE_CODE,
        "date": TARGET_DATE,
    }

    print(f"Endpoint: {API_URL}")
    print(f"Venue: {VENUE_CODE}")
    print(f"Date: {TARGET_DATE}")
    print("Proxy: NONE (direct GitHub runner request)")

    start = time.perf_counter()

    try:
        response = requests.get(
            API_URL,
            params=params,
            headers=HEADERS,
            timeout=TIMEOUT
        )

        elapsed = time.perf_counter() - start

        print(f"\nHTTP status: {response.status_code}")
        print(f"Response time: {elapsed:.2f} seconds")
        print(f"Content-Type: {response.headers.get('Content-Type')}")
        print(f"Response size: {len(response.content)} bytes")

        print_section("3. RESPONSE VALIDATION")

        try:
            data = response.json()
        except ValueError:
            print("FAIL: Response is not valid JSON.")
            print("Response preview:")
            print(response.text[:1000])
            return False

        print("Valid JSON: YES")

        show_details = data.get("ShowDetails")

        if not isinstance(show_details, list):
            print("FAIL: ShowDetails is missing or is not a list.")
            print("Top-level keys:", list(data.keys())[:30])
            print("Response preview:")
            print(json.dumps(data, indent=2)[:1500])
            return False

        print(f"ShowDetails entries: {len(show_details)}")

        matching_date = []
        matching_venue = []

        for detail in show_details:
            if str(detail.get("Date")) == TARGET_DATE:
                matching_date.append(detail)

                venues = detail.get("Venues", {})
                if isinstance(venues, dict):
                    if str(venues.get("VenueCode", "")).upper() == VENUE_CODE.upper():
                        matching_venue.append(detail)

        print(f"Matching date entries: {len(matching_date)}")
        print(f"Matching venue entries: {len(matching_venue)}")

        if response.status_code != 200:
            print("FAIL: HTTP status is not 200.")
            return False

        if not matching_date:
            print("FAIL: Requested date not found.")
            return False

        if not matching_venue:
            print("FAIL: Requested venue not found.")
            print("This could indicate incorrect parameters or a response schema change.")
            return False

        print_section("4. RESULT")

        print("SUCCESS: Direct BMS request returned validated data.")
        print(f"Runner IP: {get_public_ip() or 'Unknown'}")
        print(f"Venue: {VENUE_CODE}")
        print(f"Date: {TARGET_DATE}")

        # Save a small diagnostic sample, not the entire response.
        with open("bms_test_result.json", "w", encoding="utf-8") as file:
            json.dump(
                {
                    "tested_at": datetime.now(timezone.utc).isoformat(),
                    "status_code": response.status_code,
                    "response_time_seconds": round(elapsed, 2),
                    "runner_ip": os.getenv("RUNNER_PUBLIC_IP"),
                    "venue": VENUE_CODE,
                    "date": TARGET_DATE,
                    "show_details_count": len(show_details),
                    "venue_matches": len(matching_venue),
                    "response_preview": matching_venue[0],
                },
                file,
                indent=2,
                ensure_ascii=False,
                default=str,
            )

        print("Diagnostic file saved: bms_test_result.json")
        return True

    except requests.RequestException as exc:
        elapsed = time.perf_counter() - start
        print(f"REQUEST FAILED after {elapsed:.2f}s")
        print(f"Error: {type(exc).__name__}: {exc}")
        return False


if __name__ == "__main__":
    print_section("BOOKMYSHOW DIRECT CONNECTIVITY TEST")

    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")

    public_ip = get_public_ip()
    if public_ip:
        os.environ["RUNNER_PUBLIC_IP"] = public_ip

    success = test_bms()

    print_section("FINAL STATUS")
    print("DIRECT ACCESS: " + ("SUCCESS" if success else "FAILED"))

    if not success:
        raise SystemExit(1)
