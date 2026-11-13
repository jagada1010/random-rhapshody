
import os
import requests

from fetcher import fetch_json


def main():
    print("Testing ScraperAPI with example.com...")

    response = requests.get(
        "https://api.scraperapi.com",
        params={
            "api_key": os.getenv("SCRAPERAPI_API_KEY"),
            "url": "https://example.com/",
        },
        timeout=90,
    )

    print("ScraperAPI HTTP status:", response.status_code)
    response.raise_for_status()

    print("Example response received:")
    print(response.text[:300])

    print("\nTesting the BookMyShow endpoint...")

    data = fetch_json(
        "https://in.bookmyshow.com/api/v3/mobile/showtimes/byvenue",
        params={
            "dateCode": "20261116",
            "venueCode": "ALUC",
            "regionCode": "HYD",
        },
    )

    print("BookMyShow JSON received.")
    print("Root keys:", list(data.keys()))
    print("ShowDetails present:", "ShowDetails" in data)


if __name__ == "__main__":
    main()
