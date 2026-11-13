"""BookMyShow monitor configuration.

ACTIVE_PROFILE:
    SANITY_TEST -> Ramayana / Telugu
    REAL_DATA   -> Avengers: Doomsday / English

Only theatre codes in active_theatres_for_alert are monitored.
"""

# ============================================================
# GENERAL SETTINGS
# ============================================================

ACTIVE_PROFILE = "SANITY_TEST"

active_theatres_for_alert = ["AC", "ART", "AAA"]

REGION_CODE = "HYD"
REGION_SLUG = "hyderabad"

API_URL = "https://in.bookmyshow.com/api/v3/mobile/showtimes/byvenue"
REQUEST_TIMEOUT = 20  # Retained for compatibility with local diagnostics.
SCRAPERAPI_TIMEOUT = 90


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
    ],
    "language": "English",
    "target_dates": ["20261218", "20261219"],
}


# ============================================================
# THEATRE / PREMIUM FORMAT TARGETS
# ============================================================

THEATRE_TARGETS = {
    "AC": [
        {
            "target_id": "allu_dolby_cinema",
            "theatre_name": "Allu Cinemas",
            "venue_code": "ALUC",
            "format_label": "Dolby Cinema",
            "match_type": "DOLBY_CINEMA",
        },
    ],
    "PCX": [
        {
            "target_id": "prasads_pcx",
            "theatre_name": "Prasads Multiplex",
            "venue_code": "PRHN",
            "format_label": "PCX",
            "match_type": "PCX",
        },
        {
            "target_id": "prasads_hdr_by_barco",
            "theatre_name": "Prasads Multiplex",
            "venue_code": "PRHN",
            "format_label": "HDR by Barco",
            "match_type": "HDR_BY_BARCO",
        },
    ],
    "ART": [
        {
            "target_id": "art_epiq",
            "theatre_name": "ART Cinemas, Vanasthalipuram",
            "venue_code": "ACEV",
            "format_label": "EPIQ",
            "match_type": "EPIQ",
        },
    ],
    "AAA": [
        {
            "target_id": "aaa_led",
            "theatre_name": "AAA Cinemas, Ameerpet",
            "venue_code": "ACAS",
            "format_label": "LED",
            "match_type": "LED",
        },
    ],
}
