
from collections import defaultdict
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
import html
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


# ============================================================
# CONFIGURATION HELPERS
# ============================================================

def get_active_profile() -> dict:
    """Return the selected movie profile from config.py."""

    profile_name = config.ACTIVE_PROFILE.strip().upper()

    if profile_name not in {"SANITY_TEST", "REAL_DATA"}:
        raise ValueError(
            'ACTIVE_PROFILE must be either "SANITY_TEST" or "REAL_DATA".'
        )

    profile = getattr(config, profile_name, None)

    if not isinstance(profile, dict):
        raise ValueError(f"{profile_name} must be a dictionary in config.py.")

    required_keys = {
        "movie_title",
        "movie_aliases",
        "language",
        "target_dates",
    }

    missing = required_keys - set(profile)

    if missing:
        raise ValueError(
            f"{profile_name} is missing configuration keys: {sorted(missing)}"
        )

    return profile


def get_active_targets() -> list:
    """Expand active theatre codes into their configured screen targets."""

    active_codes = config.active_theatres_for_alert

    if not isinstance(active_codes, list) or not active_codes:
        raise ValueError(
            "active_theatres_for_alert must be a non-empty list."
        )

    targets = []

    for code in active_codes:
        if code not in config.THEATRE_TARGETS:
            raise ValueError(
                f"Unknown theatre code {code!r}. "
                f"Valid codes: {sorted(config.THEATRE_TARGETS)}"
            )

        targets.extend(config.THEATRE_TARGETS[code])

    if not targets:
        raise ValueError("No theatre targets are configured.")

    return targets


# ============================================================
# DATE VALIDATION
# ============================================================

def validate_date_format(date_code: str) -> bool:
    """Check that a date is a valid YYYYMMDD date."""

    try:
        datetime.strptime(date_code, "%Y%m%d")
        return True
    except (TypeError, ValueError):
        return False


def validate_response_date(data: dict, target_date: str) -> list:
    """
    Return only ShowDetails entries matching the requested date.

    Reject BookMyShow fallback data for another active date.
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
        and str(detail.get("Date", "")) == target_date
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


# ============================================================
# BOOKMYSHOW API
# ============================================================

def fetch_showtimes(target_date: str, venue_code: str) -> dict:
    """Fetch showtimes for one venue and one requested date."""

    params = {
        "dateCode": target_date,
        "venueCode": venue_code,
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
            f"{config.REGION_CODE}/"
            f"buytickets/{venue_code}/{target_date}"
        ),
    }

    print(f"Fetching {venue_code} for {target_date}...")

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
            f"BookMyShow returned invalid JSON for venue {venue_code}."
        ) from exc

    if not isinstance(data, dict):
        raise RuntimeError(
            f"Unexpected response format for venue {venue_code}: "
            "root is not an object."
        )

    return data


# ============================================================
# TEXT NORMALIZATION AND MATCHING
# ============================================================

def normalize(value) -> str:
    """
    Normalize text for case-insensitive and punctuation-insensitive
    comparisons.
    """

    value = unicodedata.normalize("NFKC", str(value or ""))
    value = value.casefold()
    value = re.sub(r"[^\w]+", " ", value)

    return " ".join(value.split())


def movie_matches(
    parent_event: dict,
    child_event: dict,
    profile: dict,
) -> bool:
    """Match the configured movie against parent and child event names."""

    configured_titles = [
        profile["movie_title"],
        *profile.get("movie_aliases", []),
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


def language_matches(
    child_event: dict,
    configured_language: str,
) -> bool:
    """
    Match language by containment, not exact equality.

    Configured "English" accepts:
      - English
      - English 3D
      - English Dolby 3D

    Projection format is not a language restriction.
    """

    expected_language = normalize(configured_language)

    if not expected_language:
        return False

    candidates = [
        child_event.get("EventLanguage", ""),
        child_event.get("EventName", ""),
    ]

    return any(
        expected_language in normalize(candidate)
        for candidate in candidates
        if candidate
    )


# ============================================================
# THEATRE-SPECIFIC SCREEN MATCHING
# ============================================================

def matches_target(
    target: dict,
    parent_event: dict,
    child_event: dict,
    show: dict,
) -> bool:
    """
    Apply the target's own screen/format identification rule.

    Screen names alone are not used for PCX or HDR by Barco because
    the same physical screen name can also host standard sessions.
    """

    match_type = target["match_type"]

    attributes = normalize(show.get("Attributes"))
    dimension = normalize(child_event.get("EventDimension"))
    event_name = normalize(child_event.get("EventName"))
    screen_name = normalize(show.get("ScreenName"))

    if match_type == "DOLBY_CINEMA":
        return (
            attributes == normalize("DOLBY CINEMA")
            or "dolby cinema" in dimension
            or "dolby cinema" in event_name
        )

    if match_type == "PCX":
        return attributes == normalize("PCX Screen")

    if match_type == "HDR_BY_BARCO":
        return (
            "hdr by barco" in dimension
            or "hdr by barco" in event_name
        )

    if match_type == "EPIQ":
        # Reject known conflicting attributes.
        if attributes and "epiq" not in attributes:
            return False

        return (
            "epiq" in attributes
            or "epiq" in dimension
            or "epiq" in screen_name
        )

    if match_type == "LED":
        return "led" in attributes.split()

    raise ValueError(f"Unknown match_type: {match_type}")


# ============================================================
# SHOW IDENTIFICATION
# ============================================================

def identify_shows(
    matching_details: list,
    target_date: str,
    target: dict,
    profile: dict,
) -> list:
    """Find sessions matching movie, language, date and target format."""

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

                if not movie_matches(parent_event, child_event, profile):
                    continue

                if not language_matches(
                    child_event,
                    profile["language"],
                ):
                    continue

                show_times = child_event.get("ShowTimes", [])

                if not isinstance(show_times, list):
                    continue

                for show in show_times:
                    if not isinstance(show, dict):
                        continue

                    # Reject sessions belonging to another date.
                    if str(show.get("ShowDateCode", "")) != target_date:
                        continue

                    if not matches_target(
                        target,
                        parent_event,
                        child_event,
                        show,
                    ):
                        continue

                    session_id = show.get("SessionId")
                    event_code = child_event.get("EventCode")

                    if not session_id or not event_code:
                        print(
                            "Skipping a matching-looking show because "
                            "EventCode or SessionId is missing."
                        )
                        continue

                    identified.append({
                        "target_id": target["target_id"],
                        "theatre_name": target["theatre_name"],
                        "venue_code": target["venue_code"],
                        "format_label": target["format_label"],
                        "movie": (
                            parent_event.get("EventTitle")
                            or child_event.get("EventName")
                            or profile["movie_title"]
                        ),
                        "language": (
                            child_event.get("EventLanguage")
                            or profile["language"]
                        ),
                        "dimension": child_event.get("EventDimension", ""),
                        "event_code": event_code,
                        "session_id": session_id,
                        "date": str(show.get("ShowDateCode")),
                        "time": show.get("ShowTime", "Time not provided"),
                        "screen": show.get(
                            "ScreenName",
                            "Screen not provided",
                        ),
                        "attributes": show.get("Attributes", ""),
                    })

    return identified


# ============================================================
# BOOKING URL AND CONSOLE OUTPUT
# ============================================================

def get_booking_url(show: dict) -> str:
    return (
        "https://in.bookmyshow.com/movies/"
        f"{config.REGION_SLUG}/seat-layout/"
        f"{show['event_code']}/{show['venue_code']}/"
        f"{show['session_id']}/{show['date']}"
    )


def print_results(shows: list) -> None:
    if not shows:
        print("\nNo matching sessions found.")
        return

    print(f"\nFound {len(shows)} matching session(s):\n")

    for index, show in enumerate(shows, start=1):
        print(f"--- Session {index} ---")
        print(f"Theatre:   {show['theatre_name']}")
        print(f"Format:    {show['format_label']}")
        print(f"Movie:     {show['movie']}")
        print(f"Language:  {show['language']}")
        print(f"Dimension: {show['dimension']}")
        print(f"Date:      {show['date']}")
        print(f"Time:      {show['time']}")
        print(f"Screen:    {show['screen']}")
        print(f"Event:     {show['event_code']}")
        print(f"Session:   {show['session_id']}")
        print(f"Seat URL:  {get_booking_url(show)}")
        print()


# ============================================================
# EMAIL GROUPING AND FORMATTING
# ============================================================

def group_shows(shows: list) -> dict:
    """Group sessions by theatre -> date -> screen."""

    grouped = defaultdict(
        lambda: defaultdict(
            lambda: defaultdict(list)
        )
    )

    for show in shows:
        screen_key = (
            f"{show['screen']} ({show['format_label']})"
        )

        grouped[show["theatre_name"]][show["date"]][
            screen_key
        ].append(show)

    return grouped


def build_email_body(shows: list, movie_title: str) -> str:
    """
    Build a phone-preview-friendly plain-text email.

    Structure: Theatre -> Date -> Screen -> Sessions.
    """

    grouped = group_shows(shows)

    lines = [
        f"🚨 BOOKMYSHOW ALERT: {movie_title}",
        (
            f"FOUND {len(shows)} MATCHING SHOW SESSION(S) "
            f"ACROSS {len(grouped)} THEATRE(S)."
        ),
        "",
        "Matching sessions are listed below.",
        "",
    ]

    for theatre_name in sorted(grouped):
        lines.extend([
            "=" * 58,
            f"THEATRE: {theatre_name}",
            "=" * 58,
        ])

        for date_code in sorted(grouped[theatre_name]):
            try:
                formatted_date = datetime.strptime(
                    date_code,
                    "%Y%m%d",
                ).strftime("%d %b %Y")
            except ValueError:
                formatted_date = date_code

            lines.extend(["", f"DATE: {formatted_date}"])

            for screen_name in sorted(
                grouped[theatre_name][date_code]
            ):
                lines.extend([
                    "",
                    f"  SCREEN: {screen_name}",
                ])

                sessions = grouped[theatre_name][date_code][screen_name]
                sessions.sort(key=lambda item: str(item["time"]))

                for show in sessions:
                    lines.extend([
                        f"    Movie: {show['movie']}",
                        f"    Language: {show['language']}",
                        (
                            f"    Format: "
                            f"{show['dimension'] or show['format_label']}"
                        ),
                        f"    Showtime: {show['time']}",
                        f"    Booking link: {get_booking_url(show)}",
                        "",
                    ])

    lines.extend([
        "-" * 58,
        "This is an automated BookMyShow show-identification alert.",
        "Open the booking link to verify current seat availability.",
    ])

    return "\n".join(lines)


def build_email_html(shows: list, movie_title: str) -> str:
    """Build an HTML alternative with clickable booking links."""

    grouped = group_shows(shows)

    parts = [
        "<html><body>",
        f"<h2>🚨 BOOKMYSHOW ALERT: {html.escape(movie_title)}</h2>",
        (
            f"<p><strong>Found {len(shows)} matching show session(s) "
            f"across {len(grouped)} theatre(s).</strong></p>"
        ),
    ]

    for theatre_name in sorted(grouped):
        parts.append(f"<h2>{html.escape(theatre_name)}</h2>")

        for date_code in sorted(grouped[theatre_name]):
            try:
                formatted_date = datetime.strptime(
                    date_code,
                    "%Y%m%d",
                ).strftime("%d %b %Y")
            except ValueError:
                formatted_date = date_code

            parts.append(f"<h3>{html.escape(formatted_date)}</h3>")

            for screen_name in sorted(
                grouped[theatre_name][date_code]
            ):
                parts.append(f"<h4>{html.escape(screen_name)}</h4>")
                parts.append("<ul>")

                sessions = grouped[theatre_name][date_code][screen_name]
                sessions.sort(key=lambda item: str(item["time"]))

                for show in sessions:
                    url = html.escape(
                        get_booking_url(show),
                        quote=True,
                    )

                    parts.append(
                        "<li>"
                        f"<strong>{html.escape(str(show['time']))}</strong>"
                        f" — {html.escape(str(show['movie']))}"
                        f" ({html.escape(str(show['language']))})"
                        f" — {html.escape(str(show['dimension']))}"
                        f' — <a href="{url}">BookMyShow seat layout</a>'
                        "</li>"
                    )

                parts.append("</ul>")

    parts.extend([
        "<hr>",
        "<p>Automated BookMyShow show-identification alert.</p>",
        "<p>Open the booking link to verify current seat availability.</p>",
        "</body></html>",
    ])

    return "\n".join(parts)


# ============================================================
# EMAIL DELIVERY
# ============================================================

def send_success_email(shows: list, movie_title: str) -> None:
    sender = os.getenv("BMS_EMAIL_SENDER")

    recipients_raw = os.getenv("BMS_EMAIL_RECIPIENTS", "")

    recipients = [
        address.strip()
        for address in re.split(r"[,;]", recipients_raw)
        if address.strip()
    ]

    app_password = os.getenv(
        "BMS_GMAIL_APP_PASSWORD",
        "",
    ).replace(" ", "")

    if not sender:
        raise ValueError("BMS_EMAIL_SENDER is missing from .env.")

    if not recipients:
        raise ValueError(
            "BMS_EMAIL_RECIPIENTS is missing from .env. "
            "Separate multiple addresses with commas."
        )

    if not app_password:
        raise ValueError("BMS_GMAIL_APP_PASSWORD is missing from .env.")

    theatre_count = len({
        show["theatre_name"]
        for show in shows
    })

    message = EmailMessage()

    message["Subject"] = (
        f"🚨 SHOW FOUND: {movie_title} | "
        f"{len(shows)} session(s) | {theatre_count} theatre(s)"
    )

    message["From"] = sender
    message["To"] = ", ".join(recipients)

    # Plain text is the notification preview/fallback.
    message.set_content(
        build_email_body(shows, movie_title)
    )

    # HTML version provides clickable booking links.
    message.add_alternative(
        build_email_html(shows, movie_title),
        subtype="html",
    )

    print(f"Sending email to {len(recipients)} recipient(s)...")

    with smtplib.SMTP_SSL(
        "smtp.gmail.com",
        465,
        timeout=30,
    ) as server:
        server.login(sender, app_password)

        server.send_message(
            message,
            from_addr=sender,
            to_addrs=recipients,
        )

    print("SUCCESS: Email notification sent.")


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    profile = get_active_profile()
    targets = get_active_targets()

    movie_title = profile["movie_title"]
    target_dates = profile["target_dates"]

    if not target_dates:
        raise ValueError(
            f"{config.ACTIVE_PROFILE}.target_dates is empty. "
            "Add at least one date in YYYYMMDD format in config.py."
        )

    # Validate all dates before making API requests.
    for target_date in target_dates:
        if not validate_date_format(target_date):
            raise ValueError(
                f"Invalid date: {target_date}. Use YYYYMMDD format."
            )

    if len(target_dates) != len(set(target_dates)):
        raise ValueError("target_dates contains duplicate dates.")

    # Fetch each active venue only once per date.
    # PCX has two target formats but both use venue code PRHN.
    venue_codes = list(dict.fromkeys(
        target["venue_code"]
        for target in targets
    ))

    print("\n" + "=" * 65)
    print(f"ACTIVE PROFILE: {config.ACTIVE_PROFILE}")
    print(f"MOVIE: {movie_title}")
    print(f"LANGUAGE: {profile['language']}")
    print(
        "ACTIVE THEATRE CODES: "
        f"{config.active_theatres_for_alert}"
    )
    print(f"TARGET DATES: {target_dates}")
    print(f"VENUES TO FETCH: {venue_codes}")
    print("=" * 65)

    all_shows = []

    for target_date in target_dates:
        print(f"\n{'=' * 65}")
        print(f"CHECKING DATE: {target_date}")
        print(f"{'=' * 65}")

        for venue_code in venue_codes:
            data = fetch_showtimes(
                target_date,
                venue_code,
            )

            matching_details = validate_response_date(
                data,
                target_date,
            )

            venue_targets = [
                target
                for target in targets
                if target["venue_code"] == venue_code
            ]

            for target in venue_targets:
                shows = identify_shows(
                    matching_details,
                    target_date,
                    target,
                    profile,
                )

                if shows:
                    print(
                        f"\n{target['theatre_name']} - "
                        f"{target['format_label']}: "
                        f"{len(shows)} matching session(s)"
                    )

                    print_results(shows)

                all_shows.extend(shows)

    # Remove accidental duplicates while preserving order.
    unique_shows = []
    seen = set()

    for show in all_shows:
        key = (
            show["target_id"],
            show["date"],
            str(show["session_id"]),
        )

        if key not in seen:
            seen.add(key)
            unique_shows.append(show)

    print("\n" + "=" * 65)
    print(f"TOTAL MATCHING SESSIONS: {len(unique_shows)}")
    print("=" * 65)

    if unique_shows:
        send_success_email(
            unique_shows,
            movie_title,
        )
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
        print(f"\nConfiguration/data error: {exc}")

    except (smtplib.SMTPException, OSError) as exc:
        print(f"\nEmail sending failed: {exc}")
        raise SystemExit(1)
