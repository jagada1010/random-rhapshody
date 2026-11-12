
from datetime import datetime
from pathlib import Path
from email.message import EmailMessage
import os
import re
import smtplib
import unicodedata

import requests
from dotenv import load_dotenv

import config


# Load .env from the same directory as this Python file.
ENV_FILE = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=ENV_FILE)


def validate_date_format(date_code: str) -> bool:
    """Check that a date is a valid YYYYMMDD date."""

    try:
        datetime.strptime(date_code, "%Y%m%d")
        return True
    except ValueError:
        return False


def fetch_showtimes(target_date: str) -> dict:
    """Fetch showtimes for the configured venue and date."""

    params = {
        "dateCode": target_date,
        "venueCode": config.VENUE_CODE,
        "regionCode": config.REGION_CODE,
    }

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/157.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Referer": (
            "https://in.bookmyshow.com/cinemas/"
            "HYD/allu-cinemas-kokapet/"
            f"buytickets/{config.VENUE_CODE}/{target_date}"
        ),
    }

    print(f"Fetching showtimes for {target_date}...")

    response = requests.get(
        config.API_URL,
        params=params,
        headers=headers,
        timeout=config.REQUEST_TIMEOUT,
    )

    print(f"HTTP status: {response.status_code}")

    response.raise_for_status()

    try:
        data = response.json()
    except requests.exceptions.JSONDecodeError as exc:
        raise RuntimeError(
            "The server response was not valid JSON."
        ) from exc

    if not isinstance(data, dict):
        raise RuntimeError(
            "Unexpected response format: root is not an object."
        )

    return data


def validate_response_date(data: dict, target_date: str) -> list:
    """
    Return only ShowDetails entries matching the requested date.

    Reject fallback data for a different active date.
    """

    show_details = data.get("ShowDetails")

    if not isinstance(show_details, list) or not show_details:
        raise RuntimeError(
            "Invalid response: ShowDetails is missing or empty."
        )

    matching_details = [
        detail
        for detail in show_details
        if isinstance(detail, dict)
        and detail.get("Date") == target_date
    ]

    if not matching_details:
        returned_dates = [
            detail.get("Date")
            for detail in show_details
            if isinstance(detail, dict)
        ]

        raise RuntimeError(
            f"Date mismatch. Requested {target_date}, "
            f"but response contained {returned_dates}. "
            "Rejecting fallback data."
        )

    return matching_details


def normalize(value) -> str:
    """
    Normalize text for case-insensitive and punctuation-insensitive
    comparisons.
    """

    value = unicodedata.normalize("NFKC", str(value or ""))
    value = value.casefold()
    value = re.sub(r"[^\w]+", " ", value)

    return " ".join(value.split())


def movie_matches(parent_event: dict, child_event: dict) -> bool:
    """Check primary and alternate movie titles."""

    configured_titles = [
        config.MOVIE_TITLE,
        *config.MOVIE_TITLE_ALIASES,
    ]

    candidates = [
        parent_event.get("EventTitle", ""),
        child_event.get("EventName", ""),
    ]

    normalized_candidates = [
        normalize(candidate)
        for candidate in candidates
        if candidate
    ]

    for title in configured_titles:
        normalized_title = normalize(title)

        if not normalized_title:
            continue

        if any(
            normalized_title in candidate
            for candidate in normalized_candidates
        ):
            return True

    return False


def language_matches(child_event: dict) -> bool:
    return (
        normalize(child_event.get("EventLanguage"))
        == normalize(config.LANGUAGE)
    )


def is_dolby_cinema(child_event: dict, show: dict) -> bool:
    """
    Identify Dolby Cinema using either show-level Attributes
    or child-event EventDimension.

    We do not require 3D specifically because Dolby Cinema
    may be listed with different projection variants.
    """

    attribute = normalize(show.get("Attributes"))
    dimension = normalize(child_event.get("EventDimension"))

    attribute_matches = any(
        attribute == normalize(value)
        for value in config.DOLBY_ATTRIBUTE_VALUES
    )

    dimension_matches = any(
        normalize(keyword) in dimension
        for keyword in config.DOLBY_DIMENSION_KEYWORDS
        if normalize(keyword)
    )

    return attribute_matches or dimension_matches


def identify_shows(matching_details: list, target_date: str) -> list:
    """Find matching movie, language and Dolby Cinema sessions."""

    identified = []

    for detail in matching_details:
        events = detail.get("Event", [])

        if not isinstance(events, list):
            continue

        for parent_event in events:
            if not isinstance(parent_event, dict):
                continue

            child_events = parent_event.get("ChildEvents", [])

            if not isinstance(child_events, list):
                continue

            for child_event in child_events:
                if not isinstance(child_event, dict):
                    continue

                if not movie_matches(parent_event, child_event):
                    continue

                if not language_matches(child_event):
                    continue

                show_times = child_event.get("ShowTimes", [])

                if not isinstance(show_times, list):
                    continue

                for show in show_times:
                    if not isinstance(show, dict):
                        continue

                    # Reject sessions belonging to another date.
                    if show.get("ShowDateCode") != target_date:
                        continue

                    if not is_dolby_cinema(child_event, show):
                        continue

                    session_id = show.get("SessionId")
                    event_code = child_event.get("EventCode")

                    if not session_id or not event_code:
                        print(
                            "Skipping a matching-looking show "
                            "because its identifiers are missing."
                        )
                        continue

                    identified.append({
                        "movie": parent_event.get("EventTitle"),
                        "language": child_event.get("EventLanguage"),
                        "dimension": child_event.get("EventDimension"),
                        "event_code": event_code,
                        "session_id": session_id,
                        "date": show.get("ShowDateCode"),
                        "time": show.get("ShowTime"),
                        "screen": show.get("ScreenName"),
                        "attributes": show.get("Attributes"),
                    })

    return identified


def print_results(shows: list) -> None:
    if not shows:
        print("\nNo matching Dolby Cinema sessions found.")
        return

    print(f"\nFound {len(shows)} matching session(s):\n")

    for index, show in enumerate(shows, start=1):
        print(f"--- Session {index} ---")
        print(f"Movie:     {show['movie']}")
        print(f"Language:  {show['language']}")
        print(f"Format:    {show['dimension']}")
        print(f"Date:      {show['date']}")
        print(f"Time:      {show['time']}")
        print(f"Screen:    {show['screen']}")
        print(f"Event:     {show['event_code']}")
        print(f"Session:   {show['session_id']}")

        booking_url = (
            "https://in.bookmyshow.com/movies/"
            f"{config.REGION_CODE}/seat-layout/"
            f"{show['event_code']}/{config.VENUE_CODE}/"
            f"{show['session_id']}/{show['date']}"
        )

        print(f"Seat URL:  {booking_url}")
        print()


def send_success_email(shows):
    sender = os.getenv("BMS_EMAIL_SENDER")

    recipients_raw = os.getenv("BMS_EMAIL_RECIPIENTS", "")
    recipients = [
        address.strip()
        for address in recipients_raw.split(",")
        if address.strip()
    ]

    app_password = os.getenv("BMS_GMAIL_APP_PASSWORD", "").replace(" ", "")

    if not sender:
        raise ValueError("BMS_EMAIL_SENDER is missing.")

    if not recipients:
        raise ValueError("BMS_EMAIL_RECIPIENTS is missing.")

    if not app_password:
        raise ValueError("Email authentication credential is missing.")

    message = EmailMessage()
    message["Subject"] = (
        f"BookMyShow Alert: {config.MOVIE_TITLE} - "
        f"{len(shows)} matching session(s)"
    )
    message["From"] = sender
    message["To"] = ", ".join(recipients)

    body = [
        f"Found {len(shows)} matching Dolby Cinema session(s).",
        "",
    ]

    for index, show in enumerate(shows, start=1):
        body.extend([
            f"SESSION {index}",
            f"Movie: {show['movie']}",
            f"Language: {show['language']}",
            f"Format: {show['dimension']}",
            f"Date: {show['date']}",
            f"Time: {show['time']}",
            f"Screen: {show['screen']}",
            f"Booking URL: https://in.bookmyshow.com/movies/"
            f"{config.REGION_CODE}/seat-layout/"
            f"{show['event_code']}/{config.VENUE_CODE}/"
            f"{show['session_id']}/{show['date']}",
            "",
        ])

    message.set_content("\n".join(body))

    print(f"Sending email to {len(recipients)} recipient(s)...")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
        server.login(sender, app_password)
        server.send_message(
            message,
            from_addr=sender,
            to_addrs=recipients,
        )

    print("SUCCESS: Email notification sent.")

def main():
    target_dates = config.TARGET_DATES

    if not target_dates:
        raise ValueError("TARGET_DATES cannot be empty.")

    # Validate all dates before making API requests.
    for target_date in target_dates:
        if not validate_date_format(target_date):
            raise ValueError(
                f"Invalid date: {target_date}. "
                "Use YYYYMMDD format."
            )

    if len(target_dates) != len(set(target_dates)):
        raise ValueError("TARGET_DATES contains duplicate dates.")

    all_shows = []

    for target_date in target_dates:
        print(f"\n{'=' * 50}")
        print(f"Checking date: {target_date}")
        print(f"{'=' * 50}")

        data = fetch_showtimes(target_date)

        matching_details = validate_response_date(
            data,
            target_date,
        )

        shows = identify_shows(
            matching_details,
            target_date,
        )

        print_results(shows)
        all_shows.extend(shows)

    print(f"\nTotal matching sessions: {len(all_shows)}")

    if all_shows:
        send_success_email(all_shows)
    else:
        print("No matching sessions. No email will be sent.")

        
if __name__ == "__main__":
    try:
        main()

    except requests.exceptions.HTTPError as exc:
        print(f"\nHTTP error: {exc}")

    except requests.exceptions.RequestException as exc:
        print(f"\nNetwork error: {exc}")

    except (RuntimeError, ValueError) as exc:
        print(f"\nError: {exc}")

    except (smtplib.SMTPException, OSError) as exc:
        print(f"\nEmail sending failed: {exc}")
        raise SystemExit(1)
