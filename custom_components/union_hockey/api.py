"""Client for the match schedule of unionhockey.nl (Lisa hockey API and the website's own schedule feed)."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
import logging
from typing import Any

from aiohttp import ClientError, ClientSession

from .const import (
    CLUB_NAME,
    LISA_TRAINING_URL,
    LISA_URL,
    RTS_URL,
    SITE,
)

_LOGGER = logging.getLogger(__name__)

TIMEOUT = 25
# The website refuses clients without a browser-like user agent
USER_AGENT = "Mozilla/5.0 (compatible; HomeAssistant union_hockey)"
PAGE_SIZE = 100

_MONTHS_NL = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]
_MONTHS_EN = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


class UnionHockeyError(Exception):
    """The schedule could not be read."""


def field_type(field: str | None, field_types: dict[str, str]) -> str | None:
    """'water' or 'kunstgras' for a field name of the schedule ('Austria veldC' counts as 'Austria veld')."""
    if not field:
        return None
    lowered = field.strip().lower()
    for name, kind in field_types.items():
        if lowered.startswith(name.lower()):
            return kind
    return None


def _parse_day(text: str | None) -> date | None:
    """'29-11-2026' as a date."""
    try:
        return datetime.strptime(text or "", "%d-%m-%Y").date()
    except ValueError:
        return None


def normalize_match(raw: dict[str, Any], field_types: dict[str, str], tz) -> dict[str, Any] | None:
    """One match of the schedule feed as a flat dict; None when it is no match (a booking, a training)."""
    day = _parse_day(raw.get("date"))
    if day is None or not raw.get("code"):
        return None
    # Teams of last season (z-...) and bookings are no matches
    if str(raw.get("home_team_name") or "").lower().startswith("z-") or str(raw.get("away_team_name") or "").lower().startswith("z-"):
        return None
    time_text = raw.get("time") or None
    start = None
    if time_text:
        try:
            hour, minute = (int(part) for part in time_text.split(":")[:2])
            start = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
        except ValueError:
            start = None
    home = raw.get("home_team_club_name") == CLUB_NAME
    union_team = raw.get("home_team_name") if home else raw.get("away_team_name")
    opponent = raw.get("away_team_name") if home else raw.get("home_team_name")
    opponent_club = raw.get("away_team_club_name") if home else raw.get("home_team_club_name")
    result = raw.get("result") or {}
    field = (raw.get("field") or "").strip() or None
    return {
        "id": raw.get("id"),
        "code": raw.get("code"),
        "team_id": raw.get("team_id"),
        "team": union_team,
        "opponent": opponent,
        "opponent_club": opponent_club,
        "home": home,
        "date": day.isoformat(),
        "time": time_text,
        "start": start.isoformat() if start else None,
        "arrival_time": raw.get("arrival_time"),
        "field": field,
        "field_type": field_type(field, field_types) if home else None,
        "location": (raw.get("location") or {}).get("name"),
        "city": ((raw.get("location") or {}).get("address") or {}).get("city"),
        "category": raw.get("sub_category") or raw.get("category"),
        "cancelled": bool(raw.get("is_cancelled")),
        "remarks": raw.get("extra_remarks") or raw.get("club_remarks"),
        "referees": raw.get("referees") or None,
        "score_home": result.get("homescore"),
        "score_away": result.get("awayscore"),
    }


class UnionHockeyApi:
    """Reads teams, matches and trainings."""

    def __init__(self, session: ClientSession, club_id: str, api_key: str, rts_id: str) -> None:
        self._session = session
        self._club_id = club_id
        self._rts_id = rts_id
        self._lisa_headers = {
            "Authorization": f"Basic {api_key}",
            "Referer": SITE,
            "Origin": SITE.rstrip("/"),
            "Accept": "*/*",
            "User-Agent": USER_AGENT,
        }
        self._site_headers = {"Referer": f"{SITE}wedstrijdschema", "Accept": "*/*", "User-Agent": USER_AGENT}

    async def _get(self, url: str, headers: dict[str, str], params: dict[str, Any] | None = None) -> Any:
        try:
            async with asyncio.timeout(TIMEOUT):
                response = await self._session.get(url, headers=headers, params=params)
                if response.status != 200:
                    raise UnionHockeyError(f"{response.status} from {url.split('?')[0]}")
                return await response.json(content_type=None)
        except (ClientError, TimeoutError, ValueError) as err:
            raise UnionHockeyError(f"{type(err).__name__} reading {url.split('?')[0]}") from err

    # ---- teams

    async def teams(self) -> list[dict[str, str]]:
        """Every team of the club as {id, name}, without the 'z-' leftovers of last season."""
        data = await self._get(f"{LISA_URL.format(club=self._club_id)}/teams", self._lisa_headers)
        teams = [
            {"id": item["data"]["id"], "name": item["data"]["name"].strip()}
            for item in data.get("teams", [])
            if item.get("data", {}).get("id")
        ]
        return sorted(
            (t for t in teams if not t["name"].lower().startswith("z-") and "niet spelende" not in t["name"].lower()),
            key=lambda t: t["name"].lower(),
        )

    async def standing(self, team_id: str) -> dict[str, Any] | None:
        """The row of the team in its poule, with the poule name."""
        data = await self._get(f"{LISA_URL.format(club=self._club_id)}/teams/{team_id}/poules", self._lisa_headers)
        rows = data.get("teams", [])
        for row in rows:
            if row.get("is_current"):
                table = sorted(rows, key=lambda r: r.get("position") or 99)
                return {
                    "team_name": row.get("name"),
                    "poule": row.get("poule_name"),
                    "position": row.get("position"),
                    "played": row.get("number_of_matches"),
                    "points": row.get("points"),
                    "wins": row.get("wins"),
                    "draws": row.get("draws"),
                    "losses": row.get("loses"),
                    "goals_for": row.get("goals_for"),
                    "goals_against": row.get("goals_against"),
                    "table": [
                        {
                            "position": r.get("position"),
                            "team": r.get("name"),
                            "played": r.get("number_of_matches"),
                            "points": r.get("points"),
                            "goal_balance": r.get("goal_balance"),
                            "current": bool(r.get("is_current")),
                        }
                        for r in table
                    ],
                }
        return None

    async def results(self, team_id: str, team_name: str | None, limit: int = 10) -> list[dict[str, Any]]:
        """The latest results of the team itself, newest first. Lisa returns the results of the whole poule, so only the rows of this team are kept
        (found by the name Lisa uses for the team, for example "Union D2-O"; the ids of Lisa differ from the ids of the club's team list)."""
        if not team_name:
            return []
        data = await self._get(f"{LISA_URL.format(club=self._club_id)}/teams/{team_id}/match_results", self._lisa_headers)
        rows = sorted(data.get("match_results", []), key=lambda r: r.get("date") or "", reverse=True)
        mine = []
        for row in rows:
            home = row.get("home_team_name") == team_name
            if not (home or row.get("opponent_team_name") == team_name):
                continue
            own, other = (row.get("home_score"), row.get("away_score")) if home else (row.get("away_score"), row.get("home_score"))
            outcome = None if own is None or other is None else "W" if own > other else "L" if own < other else "D"
            mine.append(
                {
                    "date": (row.get("date") or "")[:10],
                    "home_team": row.get("home_team_name"),
                    "away_team": row.get("opponent_team_name"),
                    "score_home": row.get("home_score"),
                    "score_away": row.get("away_score"),
                    "home": home,
                    "outcome": outcome,
                }
            )
        return mine[:limit]

    async def team_round(self, team_id: str) -> list[dict[str, Any]]:
        """The upcoming matches of one team straight from Lisa, with whether each is cancelled. Only the matches of the team itself."""
        data = await self._get(f"{LISA_URL.format(club=self._club_id)}/teams/{team_id}/matches_upcoming_round", self._lisa_headers)
        rows = []
        for item in data.get("matches_upcoming_round", []):
            home = bool(item.get("home_team_is_current"))
            if not (home or item.get("away_team_is_current")):
                continue
            day = _parse_day(item.get("date"))
            if day is None:
                continue
            rows.append(
                {
                    "date": day.isoformat(),
                    "time": item.get("time"),
                    "home": home,
                    "opponent": item.get("away_team_name") if home else item.get("home_team_name"),
                    "cancelled": bool(item.get("is_cancelled")),
                }
            )
        return rows

    # ---- matches

    async def _rts_collections(self) -> dict[tuple[int, int], str]:
        """The monthly collections that have matches, from the list of days with a match."""
        data = await self._get(
            RTS_URL.format(rts=self._rts_id, name="Toekomstige_wedstrijden"),
            self._site_headers,
            {"pageSize": PAGE_SIZE, "pageNumber": 0, "query": "()", "language": "DUTCH"},
        )
        found: dict[tuple[int, int], str] = {}
        for value in data.get("values", []):
            item = value.get("data", {})
            day = _parse_day(item.get("title"))
            if day and item.get("collectionname"):
                found[(day.year, day.month)] = item["collectionname"]
        return found

    async def _rts_collection_rows(self, name: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page = 0
        while True:
            data = await self._get(
                RTS_URL.format(rts=self._rts_id, name=name),
                self._site_headers,
                {"pageSize": PAGE_SIZE, "pageNumber": page, "query": "()", "language": "DUTCH"},
            )
            rows.extend(value.get("data", {}) for value in data.get("values", []))
            pages = (data.get("page") or {}).get("totalPages") or 1
            page += 1
            if page >= pages:
                return rows

    async def matches(
        self, start: date, end: date, field_types: dict[str, str], tz
    ) -> list[dict[str, Any]]:
        """Every match of the club from start to end (both included), sorted by start."""
        known = await self._rts_collections()
        months: list[tuple[int, int]] = []
        day = start.replace(day=1)
        while day <= end:
            months.append((day.year, day.month))
            day = (day.replace(day=28) + timedelta(days=4)).replace(day=1)

        matches: list[dict[str, Any]] = []
        for year, month in months:
            names = [known[(year, month)]] if (year, month) in known else [
                f"matches_{abbr}_{year}" for abbr in dict.fromkeys([_MONTHS_NL[month - 1], _MONTHS_EN[month - 1]])
            ]
            rows: list[dict[str, Any]] = []
            for name in names:
                try:
                    rows = await self._rts_collection_rows(name)
                    break
                except UnionHockeyError:
                    continue
            for raw in rows:
                match = normalize_match(raw, field_types, tz)
                if match and start.isoformat() <= match["date"] <= end.isoformat():
                    matches.append(match)
        matches.sort(key=lambda m: (m["date"], m["time"] or "99:99", m["team"] or ""))
        return matches

    # ---- trainings

    async def trainings(self, start: date, end: date, tz) -> list[dict[str, Any]]:
        """Outdoor trainings from start to end, sorted by start."""
        data = await self._get(
            LISA_TRAINING_URL.format(club=self._club_id),
            {**self._lisa_headers},
            {"start": start.strftime("%m/%d/%Y"), "end": end.strftime("%m/%d/%Y")},
        )
        result = []
        for item in data.get("trainings", []):
            if item.get("indoor") or not item.get("start_utc"):
                continue
            begin = datetime.fromisoformat(item["start_utc"].replace("Z", "+00:00")).astimezone(tz)
            finish = datetime.fromisoformat(item["end_utc"].replace("Z", "+00:00")).astimezone(tz)
            result.append(
                {
                    "team_id": item.get("team_id") if item.get("team_id") != "00000000-0000-0000-0000-000000000000" else None,
                    "team": item.get("team") or item.get("blocking_name") or None,
                    "field": item.get("field"),
                    "start": begin.isoformat(),
                    "end": finish.isoformat(),
                    "cancelled": bool(item.get("cancelled")),
                    "comment": (item.get("comment") or "").strip() or None,
                    "trainers": item.get("trainers"),
                }
            )
        result.sort(key=lambda t: t["start"])
        return result

