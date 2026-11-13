
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import json
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
from fetcher import fetch_json
from state_store import MonitorState


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


def validate_response_date(
    data: dict, target_date: str, venue_code: str | None = None
) -> list:
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

    # The current BookMyShow schema puts events directly under each
    # ShowDetails entry, not under Venues. Validate that schema before
    # allowing this snapshot to update the persistent archive.
    for detail in matching_details:
        if not isinstance(detail.get("Event"), list):
            raise RuntimeError(
                f"Invalid response for {venue_code or 'venue'} / {target_date}: "
                "ShowDetails entry is missing its Event list."
            )

        if venue_code:
            venue = detail.get("Venues")
            returned_venue = venue.get("VenueCode") if isinstance(venue, dict) else None
            if str(returned_venue or "").upper() != venue_code.upper():
                raise RuntimeError(
                    f"Venue mismatch. Requested {venue_code}, "
                    f"but response contained {returned_venue!r}. "
                    "Rejecting response."
                )

    return matching_details


# ============================================================
# BOOKMYSHOW API
# ============================================================

def fetch_showtimes(target_date: str, venue_code: str) -> dict:
    """Fetch one venue/date through ScraperAPI and return BookMyShow JSON."""

    params = {
        "dateCode": target_date,
        "venueCode": venue_code,
        "regionCode": config.REGION_CODE,
    }

    print(
        f"Fetching {venue_code} for {target_date} "
        "through ScraperAPI..."
    )

    data = fetch_json(
        target_url=config.API_URL,
        params=params,
        timeout=getattr(config, "SCRAPERAPI_TIMEOUT", 90),
    )

    print(f"Successfully received JSON for {venue_code} / {target_date}.")
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
# PROFILE STATE KEY
# ============================================================

def _profile_state_key(profile: dict, targets: list) -> str:
    """
    Keep SANITY_TEST and REAL_DATA archives separate.

    Dates are intentionally excluded so adding/removing target dates
    does not create a new archive or erase previous history.
    """
    payload = {
        "movie_title": normalize(profile["movie_title"]),
        "language": normalize(profile["language"]),
        "target_ids": sorted(
            target["target_id"] for target in targets
        ),
    }

    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
    )


# ============================================================
# MAIN MONITOR
# ============================================================

def main() -> None:
    profile = get_active_profile()
    targets = get_active_targets()

    movie_title = profile["movie_title"]
    target_dates = profile["target_dates"]

    if not target_dates:
        raise ValueError(
            f"{config.ACTIVE_PROFILE}.target_dates is empty."
        )

    for target_date in target_dates:
        if not validate_date_format(target_date):
            raise ValueError(
                f"Invalid date: {target_date}. Use YYYYMMDD format."
            )

    if len(target_dates) != len(set(target_dates)):
        raise ValueError(
            "target_dates contains duplicate dates."
        )

    venue_codes = list(dict.fromkeys(
        target["venue_code"] for target in targets
    ))

    print("\n" + "=" * 65)
    print(f"ACTIVE PROFILE: {config.ACTIVE_PROFILE}")
    print(f"MOVIE: {movie_title}")
    print(f"LANGUAGE: {profile['language']}")
    print(
        f"ACTIVE THEATRE CODES: "
        f"{config.active_theatres_for_alert}"
    )
    print(f"TARGET DATES: {target_dates}")
    print(f"VENUES TO FETCH: {venue_codes}")
    print("=" * 65)

    all_shows = []
    successful_scopes = set()
    failed_scopes = []

    # Each venue/date is an independent scope.
    # A failure in one scope must not prevent other scopes from updating.
    for target_date in target_dates:
        print(
            f"\n{'=' * 65}\n"
            f"CHECKING DATE: {target_date}\n"
            f"{'=' * 65}"
        )

        for venue_code in venue_codes:
            scope_label = f"{venue_code} / {target_date}"

            try:
                data = fetch_showtimes(
                    target_date,
                    venue_code,
                )

                matching_details = validate_response_date(
                    data,
                    target_date,
                    venue_code,
                )

                venue_targets = [
                    target
                    for target in targets
                    if target["venue_code"] == venue_code
                ]

                scope_shows = []

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

                    scope_shows.extend(shows)

                # Mark the scope successful only after fetching,
                # validating and identifying all its configured targets.
                successful_scopes.add(
                    (venue_code, target_date)
                )
                all_shows.extend(scope_shows)

                print(
                    f"SUCCESS: {scope_label} validated. "
                    f"{len(scope_shows)} matching session(s)."
                )

            except Exception as exc:
                failed_scopes.append({
                    "venue_code": venue_code,
                    "date": target_date,
                    "error": str(exc),
                })

                print(
                    f"\nWARNING: Failed to process {scope_label}."
                )
                print(f"Reason: {exc}")
                print(
                    "Previous state for this venue/date will be "
                    "preserved. Continuing with other venues."
                )

    # If every scope failed, do not touch persistent state.
    if not successful_scopes:
        details = "; ".join(
            f"{item['venue_code']}/{item['date']}: {item['error']}"
            for item in failed_scopes
        )

        raise RuntimeError(
            "All venue/date requests failed validation or fetching. "
            "Persistent state was not modified. "
            f"Failures: {details}"
        )

    # Deduplicate sessions.
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
    print(
        f"SUCCESSFUL VENUE/DATE SCOPES: "
        f"{len(successful_scopes)}"
    )
    print(
        f"FAILED VENUE/DATE SCOPES: "
        f"{len(failed_scopes)}"
    )
    print("=" * 65)

    if failed_scopes:
        print("\nPARTIAL FETCH WARNING:")
        for item in failed_scopes:
            print(
                f"  - {item['venue_code']} / {item['date']}: "
                f"{item['error']}"
            )

    timezone_name = os.getenv(
        "BMS_TIMEZONE",
        "Asia/Kolkata",
    )
    now = datetime.now(ZoneInfo(timezone_name))

    state_file = Path(
        os.getenv(
            "BMS_STATE_FILE",
            "state/state.json",
        )
    )

    state = MonitorState(state_file)

    profile_key = _profile_state_key(
        profile,
        targets,
    )

    # Commit only validated scopes. Failed scopes are untouched.
    result = state.record_partial_snapshot(
        profile_key=profile_key,
        shows=unique_shows,
        successful_scopes=successful_scopes,
        now=now,
    )

    print(
        f"\nPersistent state updated: {state_file}"
    )
    print(
        f"Archived sessions: {len(result['archive'])}"
    )
    print(
        f"Pending notification changes: "
        f"{len(result['pending_changes'])}"
    )

    # No pending new/reappeared/updated sessions means no email.
    # This applies 24/7; there is no sleep-hour throttle.
    if not result["pending_changes"]:
        print(
            "\nNo new, reappeared or changed sessions. "
            "No email will be sent."
        )
        raise SystemExit(1)

    # Email contains all currently listed sessions for the dates
    # configured in this run, not just the latest delta.
    #
    # This also includes last-known sessions from failed scopes,
    # because their previous state is deliberately preserved.
    active_dates = {str(date) for date in target_dates}

    current_shows = [
        record
        for record in result["archive"]
        if (
            record.get("status") == "currently_listed"
            and str(record.get("date", "")) in active_dates
        )
    ]

    current_shows.sort(
        key=lambda show: (
            str(show.get("date", "")),
            str(show.get("theatre_name", "")),
            str(show.get("screen", "")),
            str(show.get("time", "")),
        )
    )

    print(
        f"\nChanges detected: "
        f"{len(result['pending_changes'])}"
    )
    print(
        f"Currently listed sessions included in email: "
        f"{len(current_shows)}"
    )

    if failed_scopes:
        print(
            "NOTE: The email may include last-known sessions "
            "from venue/date scopes that failed during this run."
        )

    # Send at most one email per run.
    # If SMTP fails, pending_changes are NOT cleared.
    send_success_email(
        current_shows,
        movie_title,
    )

    # Clear pending changes only after successful email delivery.
    state.clear_pending_changes(profile_key)

    print(
        "Notification changes cleared after successful email delivery."
    )


if __name__ == "__main__":
    try:
        main()

    except requests.exceptions.HTTPError as exc:
        print(f"\nHTTP error: {exc}")
        raise SystemExit(1)

    except requests.exceptions.RequestException as exc:
        print(f"\nNetwork error: {exc}")
        raise SystemExit(1)

    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"\nConfiguration/data error: {exc}")
        raise SystemExit(1)

    except (smtplib.SMTPException, OSError) as exc:
        print(f"\nEmail/state operation failed: {exc}")
        raise SystemExit(1)
