"""BookMyShow monitor configuration.

ACTIVE_PROFILE:
    SANITY_TEST -> Ramayana / Telugu
    REAL_DATA   -> Avengers: Doomsday / English

Only theatre codes in active_theatres_for_alert are monitored.

Matching configuration:
    format_label: list of accepted text variants from BookMyShow.
    match_type:   list of matching modes; values are PARTIAL, EXACT or WORD.
    match_fields: JSON fields to inspect for the format variants.

Matching behaviour is OR-based: any configured format_label matching any
configured field using any configured match_type is sufficient.
"""

# ============================================================
# GENERAL SETTINGS
# ============================================================

ACTIVE_PROFILE = "REAL_DATA"

# Only these theatre codes are fetched and included in alerts.
active_theatres_for_alert = ["AC", "PCX"]

REGION_CODE = "HYD"
REGION_SLUG = "hyderabad"

API_URL = "https://in.bookmyshow.com/api/v3/mobile/showtimes/byvenue"
REQUEST_TIMEOUT = 20


# ============================================================
# SANITY TEST
# ============================================================

SANITY_TEST = {
    "movie_title": "Ramayana",
    "movie_aliases": [],
    "language": "Telugu",
    "target_dates": ["20261117"],
}


# ============================================================
# REAL MONITORING
# ============================================================

REAL_DATA = {
    "movie_title": "Avengers: Doomsday",
    "movie_aliases": [
        "Avengers Doomsday",
        "Avengers: Doomsday",
        "Avengers",
        "Doomsday",
    ],
    "language": "English",
    "target_dates": ["20261218"],
}


# ============================================================
# THEATRE / PREMIUM FORMAT TARGETS
# ============================================================

THEATRE_TARGETS = {
    "AC": [
        {
            # Keep the existing target_id so the profile's state key remains
            # compatible with the existing archive.
            "target_id": "allu_dolby_cinema",
            "theatre_name": "Allu Cinemas",
            "venue_code": "ALUC",
            "display_label": "Dolby Cinema / MS Infinity Vision",
            "format_label": [
                "DOLBY CINEMA",
                "DOLBY 3D",
                "VISION",
                "DOLBY",
                "DOLBY CINEMA 3D",
                "MS-INFINITY VSN",
                "MS-INFINITY VSN 3D",
                "INFINITY",
                "INF VSN",
                "VSN",
                "MS-INFINITY VISION",
                "MS - Infinity Vision",
                "MS-INFINITY VISION 3D",
            ],
            "match_type": ["PARTIAL"],
            "match_fields": ["Attributes", "EventDimension", "EventName"],
        },
    ],
    "PCX": [
        {
            "target_id": "prasads_pcx",
            "theatre_name": "Prasads Multiplex",
            "venue_code": "PRHN",
            "display_label": "PCX",
            "format_label": ["PCX Screen",                 "MS-INFINITY VSN",
                "MS-INFINITY VSN 3D",
                "INFINITY",
                "INF VSN",
                "VSN",
                "MS-INFINITY VISION",
                "MS - Infinity Vision",
                "MS-INFINITY VISION 3D",],
            "match_type": ["PARTIAL"],
            "match_fields": ["Attributes"],
        },
        {
            "target_id": "prasads_hdr_by_barco",
            "theatre_name": "Prasads Multiplex",
            "venue_code": "PRHN",
            "display_label": "HDR by Barco",
            "format_label": ["HDR by Barco",                "MS-INFINITY VSN",
                "MS-INFINITY VSN 3D",
                "INFINITY",
                "INF VSN",
                "VSN",
                "MS-INFINITY VISION",
                "MS - Infinity Vision",
                "MS-INFINITY VISION 3D",],
            "match_type": ["PARTIAL"],
            "match_fields": ["EventDimension", "EventName"],
        },
    ],
    "ART": [
        {
            "target_id": "art_epiq",
            "theatre_name": "ART Cinemas, Vanasthalipuram",
            "venue_code": "ACEV",
            "display_label": "EPIQ",
            "format_label": ["EPIQ"],
            "match_type": ["PARTIAL"],
            "match_fields": ["Attributes", "EventDimension", "ScreenName"],
            "reject_conflicting_attributes": True,
        },
    ],
    "AAA": [
        {
            "target_id": "aaa_led",
            "theatre_name": "AAA Cinemas, Ameerpet",
            "venue_code": "ACAS",
            "display_label": "LED",
            "format_label": ["LED"],
            "match_type": ["WORD"],
            "match_fields": ["Attributes"],
        },
    ],
}
