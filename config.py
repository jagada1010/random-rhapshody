"""
BookMyShow monitor configuration.

Choose which movie profile to run with ACTIVE_PROFILE:
    "SANITY_TEST" -> Ramayana / Telugu
    "REAL_DATA"   -> Avengers: Doomsday / English

Only theatre codes listed in ACTIVE_THEATRES_FOR_ALERT are monitored.
"""

# ============================================================
# GENERAL SETTINGS
# ============================================================

ACTIVE_PROFILE = "SANITY_TEST"
# ACTIVE_PROFILE = "REAL_DATA"

active_theatres_for_alert = ["AC", "PCX", "ART", "AAA"]

REGION_CODE = "HYD"
REGION_SLUG = "hyderabad"

API_URL = "https://in.bookmyshow.com/api/v3/mobile/showtimes/byvenue"
REQUEST_TIMEOUT = 20


# ============================================================
# SANITY TEST CONFIGURATION
# Add the date on which you want to test Ramayana Telugu.
# Date format: YYYYMMDD
# ============================================================

SANITY_TEST = {
    "movie_title": "Scene",
    "movie_aliases": [],
    "language": "Telugu",
    "target_dates": [
        "20261116", 
        # Example: "20261115"
    ],
}


# ============================================================
# REAL MONITORING CONFIGURATION
# Avengers: Doomsday - English in any English variant.
# English 3D / English Dolby 3D are accepted too.
# ============================================================

REAL_DATA = {
    "movie_title": "Avengers: Doomsday",
    "movie_aliases": [
        "Avengers Doomsday",
        "Avengers: Doomsday",
    ],
    "language": "English",
    "target_dates": [
        "20261218",
        "20261219",
    ],
}


# ============================================================
# THEATRE / PREMIUM SCREEN MATCHING RULES
#
# PCX includes TWO distinct formats at Prasads:
#   - PCX
#   - HDR by Barco
#
# These are separate targets but share venue code PRHN.
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
