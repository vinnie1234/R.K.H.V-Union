"""Sensors: the home matches, the trainings and one sensor per tracked team."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util, slugify

from .const import CLUB_NAME, DOMAIN
from .coordinator import UnionHockeyCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: UnionHockeyCoordinator = entry.runtime_data
    entities: list[SensorEntity] = [HomeMatchesSensor(coordinator, entry), TrainingsSensor(coordinator, entry)]
    entities.extend(TeamSensor(coordinator, entry, team["id"], team["name"]) for team in coordinator.teams)
    async_add_entities(entities)


class UnionEntity(CoordinatorEntity[UnionHockeyCoordinator], SensorEntity):
    """Common base: one device for the club."""

    _attr_has_entity_name = False
    # The lists are big and change every refresh; they do not belong in the history
    _unrecorded_attributes = frozenset({"matches", "trainings", "results", "table", "next_match"})

    def __init__(self, coordinator: UnionHockeyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=CLUB_NAME,
            manufacturer="KNHB / Lisa hockey",
            entry_type=DeviceEntryType.SERVICE,
        )


class HomeMatchesSensor(UnionEntity):
    """Upcoming home matches of the club (the matches that the club can call off)."""

    _attr_icon = "mdi:hockey-sticks"
    _attr_native_unit_of_measurement = "wedstrijden"

    def __init__(self, coordinator: UnionHockeyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Union thuiswedstrijden"
        self._attr_unique_id = f"{entry.entry_id}_home_matches"
        self.entity_id = "sensor.union_thuiswedstrijden"

    @property
    def native_value(self) -> int | None:
        return len(self.coordinator.data["home"]) if self.coordinator.data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        return {
            "matches": data.get("home", []),
            "days_ahead": self.coordinator.days_ahead,
            "field_types": self.coordinator.field_types,
        }


class TrainingsSensor(UnionEntity):
    """The coming trainings of the club."""

    _attr_icon = "mdi:run"
    _attr_native_unit_of_measurement = "trainingen"

    def __init__(self, coordinator: UnionHockeyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Union trainingen"
        self._attr_unique_id = f"{entry.entry_id}_trainings"
        self.entity_id = "sensor.union_trainingen"

    @property
    def native_value(self) -> int | None:
        return len(self.coordinator.data["trainings"]) if self.coordinator.data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"trainings": (self.coordinator.data or {}).get("trainings", [])}


class TeamSensor(UnionEntity):
    """A tracked team: its next match as the state, everything else of the team as attributes."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:account-group"

    def __init__(self, coordinator: UnionHockeyCoordinator, entry: ConfigEntry, team_id: str, name: str) -> None:
        super().__init__(coordinator, entry)
        self._team_id = team_id
        self._attr_name = f"Union {name}"
        self._attr_unique_id = f"{entry.entry_id}_team_{team_id}"
        self.entity_id = f"sensor.union_{slugify(name)}"

    @property
    def _team(self) -> dict[str, Any] | None:
        return ((self.coordinator.data or {}).get("teams") or {}).get(self._team_id)

    def _upcoming(self) -> list[dict[str, Any]]:
        today = dt_util.now().date().isoformat()
        return [m for m in (self._team or {}).get("matches", []) if m["date"] >= today]

    @property
    def native_value(self) -> datetime | None:
        now = dt_util.now()
        for match in self._upcoming():
            if match["start"] and datetime.fromisoformat(match["start"]) >= now:
                return datetime.fromisoformat(match["start"])
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        team = self._team or {}
        upcoming = self._upcoming()
        standing = team.get("standing") or {}
        return {
            "team_id": self._team_id,
            "team": team.get("name"),
            "person": team.get("person"),
            "next_match": upcoming[0] if upcoming else None,
            "matches": upcoming,
            "results": team.get("results", []),
            "trainings": team.get("trainings", []),
            "poule": standing.get("poule"),
            "position": standing.get("position"),
            "played": standing.get("played"),
            "points": standing.get("points"),
            "wins": standing.get("wins"),
            "draws": standing.get("draws"),
            "losses": standing.get("losses"),
            "table": standing.get("table", []),
        }
