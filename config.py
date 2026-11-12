
VENUE_CODE = "ALUC"
REGION_CODE = "HYD"

# Target date in YYYYMMDD format.
# TARGET_DATES = [
#     "20261217",
#     "20261218",
#     "20261219",
# ]
TARGET_DATES = ["20261113", "20261114"]

# Movie identification.
MOVIE_TITLE = "Ramayana"

# Add alternate spellings or titles if BookMyShow uses them.
# Example: ["Avengers Doomsday", "Avengers: Doomsday"]'
# MOVIE_TITLE = "Avengers: Doomsday"
# MOVIE_TITLE_ALIASES = [
#     "Avengers Doomsday",
#     "AVENGERS; DOOMSDAY",
# ]
# LANGUAGE = "English"
MOVIE_TITLE_ALIASES = []

LANGUAGE = "Telugu"

# Dolby Cinema identification.
# A match in either field is sufficient because BookMyShow
# may expose the format in either Attributes or EventDimension.
DOLBY_ATTRIBUTE_VALUES = [
    "DOLBY CINEMA",
]

DOLBY_DIMENSION_KEYWORDS = [
    "DOLBY CINEMA",
]

API_URL = "https://in.bookmyshow.com/api/v3/mobile/showtimes/byvenue"

REQUEST_TIMEOUT = 20
