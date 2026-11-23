"""Fetches the schedule of the club and of the tracked teams."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
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
            matches = await self.api.matches(today, end, self.field_types, tz)
            trainings = await self.api.trainings(today, today + timedelta(days=TRAINING_DAYS), tz)
        except UnionHockeyError as err:
            raise UpdateFailed(str(err)) from err

        now = dt_util.now().isoformat()
        home = [m for m in matches if m["home"] and (m["start"] or m["date"]) >= now[:10]]

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
        return {"home": home, "trainings": trainings, "teams": teams}
