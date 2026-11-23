"""Fetches the schedule of the club and of the tracked teams."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import UnionHockeyApi, UnionHockeyError
from .const import (
    CONF_API_KEY,
    CONF_CLUB_ID,
    CONF_DAYS_AHEAD,
    CONF_FIELD_TYPES,
    CONF_INTERVAL,
    CONF_PERSONS,
    CONF_RTS_ID,
    CONF_TEAMS,
    DEFAULT_DAYS_AHEAD,
    DEFAULT_FIELD_TYPES,
    DEFAULT_INTERVAL,
    DEFAULT_RTS_ID,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

TRAINING_DAYS = 14
LOOK_BACK_DAYS = 7      # the cancellations of the last days are shown
KEEP_DAYS = 14          # remembered cancellations are dropped after this
STORAGE_VERSION = 1
RESULTS_LIMIT = 10


class UnionHockeyCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """One refresh gets the home matches, the trainings and, per tracked team, everything of that team."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        options = {**entry.data, **entry.options}
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=int(options.get(CONF_INTERVAL, DEFAULT_INTERVAL))),
        )
        self.entry = entry
        # The feeds may drop a cancelled match once its day has passed; every cancellation that is seen is remembered here
        self._store: Store[dict[str, dict[str, Any]]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.cancelled")
        self._seen: dict[str, dict[str, Any]] | None = None
        self.days_ahead = int(options.get(CONF_DAYS_AHEAD, DEFAULT_DAYS_AHEAD))
        self.field_types: dict[str, str] = {**DEFAULT_FIELD_TYPES, **options.get(CONF_FIELD_TYPES, {})}
        # [{id, name}] of the tracked teams, and the person that plays in a team: {team id: person entity}
        self.teams: list[dict[str, str]] = list(options.get(CONF_TEAMS, []))
        self.persons: dict[str, str] = dict(options.get(CONF_PERSONS, {}))
        self.api = UnionHockeyApi(
            async_get_clientsession(hass),
            options[CONF_CLUB_ID],
            options[CONF_API_KEY],
            options.get(CONF_RTS_ID, DEFAULT_RTS_ID),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        tz = dt_util.get_default_time_zone()
        today = dt_util.now().date()
        end = today + timedelta(days=self.days_ahead)
        try:
            matches = await self.api.matches(today - timedelta(days=LOOK_BACK_DAYS), end, self.field_types, tz)
            trainings = await self.api.trainings(today, today + timedelta(days=TRAINING_DAYS), tz)
        except UnionHockeyError as err:
            raise UpdateFailed(str(err)) from err

        await self._async_apply_lisa_cancellations(matches)

        today_text = today.isoformat()
        tracked_ids = {t["id"] for t in self.teams}
        matters = lambda m: m["home"] or m["team_id"] in tracked_ids  # noqa: E731
        upcoming = [m for m in matches if m["date"] >= today_text]
        home = [m for m in upcoming if m["home"]]
        recent_cancelled = await self._async_remember_cancellations([m for m in matches if m["cancelled"] and matters(m)], today)

        cancelled = [m for m in upcoming if m["cancelled"] and matters(m)]

        teams: dict[str, dict[str, Any]] = {}
        for team in self.teams:
            team_id = team["id"]
            # Standings and results are extras: a failure there keeps the rest of the team
            try:
                standing = await self.api.standing(team_id)
            except UnionHockeyError as err:
                _LOGGER.debug("No standing for %s: %s", team["name"], err)
                standing = None
            try:
                results = await self.api.results(team_id, RESULTS_LIMIT)
            except UnionHockeyError as err:
                _LOGGER.debug("No results for %s: %s", team["name"], err)
                results = []
            teams[team_id] = {
                "name": team["name"],
                "person": self.persons.get(team_id),
                "matches": [m for m in matches if m["team_id"] == team_id],
                "trainings": [t for t in trainings if t["team_id"] == team_id],
                "standing": standing,
                "results": results,
            }
        return {"home": home, "cancelled": cancelled, "recent_cancelled": recent_cancelled, "trainings": trainings, "teams": teams}

    async def _async_remember_cancellations(self, seen_now: list[dict[str, Any]], today) -> list[dict[str, Any]]:
        """Remember the cancellations that are seen and return those of the last days (today included), newest first."""
        if self._seen is None:
            self._seen = await self._store.async_load() or {}
        changed = False
        for match in seen_now:
            key = f"{match['date']}|{match['team_id']}|{(match['opponent'] or '').lower()}"
            if self._seen.get(key) != match:
                self._seen[key] = match
                changed = True
        limit = (today - timedelta(days=KEEP_DAYS)).isoformat()
        for key in [k for k, m in self._seen.items() if m["date"] < limit]:
            del self._seen[key]
            changed = True
        if changed:
            await self._store.async_save(self._seen)
        first, last = (today - timedelta(days=LOOK_BACK_DAYS)).isoformat(), today.isoformat()
        recent = [m for m in self._seen.values() if first <= m["date"] <= last]
        return sorted(recent, key=lambda m: (m["date"], m["time"] or ""), reverse=True)

    async def _async_apply_lisa_cancellations(self, matches: list[dict[str, Any]]) -> None:
        """The website's schedule lags behind Lisa. Lisa is asked per team (home matches and followed teams) and wins when it says cancelled."""
        tracked = {team["id"] for team in self.teams}
        today = dt_util.now().date().isoformat()
        team_ids = {m["team_id"] for m in matches if m["team_id"] and m["date"] >= today and (m["home"] or m["team_id"] in tracked)}
        gate = asyncio.Semaphore(4)

        async def fetch(team_id: str) -> tuple[str, list[dict[str, Any]] | None]:
            async with gate:
                try:
                    return team_id, await self.api.team_round(team_id)
                except UnionHockeyError as err:
                    _LOGGER.debug("No round from Lisa for %s: %s", team_id, err)
                    return team_id, None

        rounds = dict(await asyncio.gather(*(fetch(team_id) for team_id in team_ids)))
        for match in (m for m in matches if m["date"] >= today):
            rows = rounds.get(match["team_id"])
            match["lisa_checked"] = rows is not None
            if not rows:
                continue
            opponent = (match["opponent"] or "").strip().lower()
            same_day = [row for row in rows if row["date"] == match["date"]]
            # By opponent; the names of two Union teams playing each other differ between the schedule and Lisa, so then the only match of that day counts
            row = next((r for r in same_day if (r["opponent"] or "").strip().lower() == opponent), None)
            if row is None:
                same_side = [r for r in same_day if r["home"] == match["home"]]
                row = same_side[0] if len(same_side) == 1 else None
            if row and row["cancelled"] and not match["cancelled"]:
                match["cancelled"] = True
                match["cancelled_source"] = "lisa"
