"""Constants for the R.K.H.V. Union Hockey integration."""

DOMAIN = "union_hockey"

CONF_CLUB_ID = "club_id"
CONF_API_KEY = "api_key"
CONF_RTS_ID = "rts_id"
CONF_DAYS_AHEAD = "days_ahead"
CONF_INTERVAL = "interval_min"
CONF_TEAMS = "teams"
CONF_PERSONS = "persons"
CONF_FIELD_TYPES = "field_types"

# The ids and the key below are the ones the public website unionhockey.nl sends to every visitor of the match schedule
DEFAULT_CLUB_ID = "b269c36d-f39f-42c7-beb6-5515e44d433d"
DEFAULT_API_KEY = "SEgxMVFOMzplM2U0ZDE1Zi1iYWJiLTRlYmUtOWNlMi00ZmM4YjYxY2RhZjI="
DEFAULT_RTS_ID = "532c65e3"
DEFAULT_DAYS_AHEAD = 14
DEFAULT_INTERVAL = 30

CLUB_NAME = "R.K.H.V. Union"

LISA_URL = "https://api.lisahockey.nl/v1/duda/{club}"
LISA_TRAINING_URL = "https://api.lisahockey.nl/api/v1/duda/{club}/training_schedule"
RTS_URL = "https://www.unionhockey.nl/rts/collections/public/{rts}/runtime/collection/{name}/query-data"
SITE = "https://www.unionhockey.nl/"

FIELD_WATER = "water"
FIELD_ARTIFICIAL = "kunstgras"

# The four fields of the club (the name as the schedule shows it; 'Austria veldC' etc. are parts of the Austria field).
FIELDS = {
    "A": "Rabobank-veld",
    "B": "B-veld",
    "C": "C-veld",
    "D": "Austria veld",
}
DEFAULT_FIELD_TYPES = {
    "Rabobank-veld": FIELD_WATER,
    "B-veld": FIELD_WATER,
    "C-veld": FIELD_ARTIFICIAL,
    "Austria veld": FIELD_ARTIFICIAL,
}
