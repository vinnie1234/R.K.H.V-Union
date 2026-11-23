"""Setup and options of the R.K.H.V. Union Hockey integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

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
    DEFAULT_API_KEY,
    DEFAULT_CLUB_ID,
    DEFAULT_DAYS_AHEAD,
    DEFAULT_FIELD_TYPES,
    DEFAULT_INTERVAL,
    DEFAULT_RTS_ID,
    DOMAIN,
    FIELD_ARTIFICIAL,
    FIELD_WATER,
    FIELDS,
)

FIELD_TYPE_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=[FIELD_WATER, FIELD_ARTIFICIAL],
        translation_key="field_type",
        mode=selector.SelectSelectorMode.DROPDOWN,
    )
)


class UnionHockeyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Connect to the schedule of the club."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_CLUB_ID])
            self._abort_if_unique_id_configured()
            api = UnionHockeyApi(
                async_get_clientsession(self.hass),
                user_input[CONF_CLUB_ID],
                user_input[CONF_API_KEY],
                user_input[CONF_RTS_ID],
            )
            try:
                if not await api.teams():
                    errors["base"] = "no_teams"
            except UnionHockeyError:
                errors["base"] = "cannot_connect"
            if not errors:
                return self.async_create_entry(title="R.K.H.V. Union", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_CLUB_ID, default=DEFAULT_CLUB_ID): str,
                vol.Required(CONF_API_KEY, default=DEFAULT_API_KEY): str,
                vol.Required(CONF_RTS_ID, default=DEFAULT_RTS_ID): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return UnionHockeyOptionsFlow()


class UnionHockeyOptionsFlow(OptionsFlow):
    """Days ahead, the field types, and the teams to track (with the person that plays in a team)."""

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}
        self._teams: list[dict[str, str]] = []

    @property
    def _current(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        current = self._current
        api = UnionHockeyApi(
            async_get_clientsession(self.hass),
            current[CONF_CLUB_ID],
            current[CONF_API_KEY],
            current.get(CONF_RTS_ID, DEFAULT_RTS_ID),
        )
        try:
            self._teams = await api.teams()
        except UnionHockeyError:
            return self.async_abort(reason="cannot_connect")

        field_types = {**DEFAULT_FIELD_TYPES, **current.get(CONF_FIELD_TYPES, {})}
        tracked_ids = [team["id"] for team in current.get(CONF_TEAMS, [])]

        if user_input is not None:
            by_id = {team["id"]: team for team in self._teams}
            self._options = {
                CONF_DAYS_AHEAD: int(user_input[CONF_DAYS_AHEAD]),
                CONF_INTERVAL: int(user_input[CONF_INTERVAL]),
                CONF_FIELD_TYPES: {name: user_input[f"field_{letter}"] for letter, name in FIELDS.items()},
                CONF_TEAMS: [by_id[team_id] for team_id in user_input.get(CONF_TEAMS, []) if team_id in by_id],
            }
            if self._options[CONF_TEAMS]:
                return await self.async_step_persons()
            self._options[CONF_PERSONS] = {}
            return self.async_create_entry(data=self._options)

        schema: dict[Any, Any] = {
            vol.Required(CONF_DAYS_AHEAD, default=current.get(CONF_DAYS_AHEAD, DEFAULT_DAYS_AHEAD)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=60, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_INTERVAL, default=current.get(CONF_INTERVAL, DEFAULT_INTERVAL)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=5, max=720, unit_of_measurement="min", mode=selector.NumberSelectorMode.BOX)
            ),
        }
        for letter, name in FIELDS.items():
            schema[vol.Required(f"field_{letter}", default=field_types.get(name, FIELD_ARTIFICIAL))] = FIELD_TYPE_SELECTOR
        schema[vol.Optional(CONF_TEAMS, default=tracked_ids)] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[selector.SelectOptionDict(value=team["id"], label=team["name"]) for team in self._teams],
                multiple=True,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))

    async def async_step_persons(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Per tracked team the person that plays in it (optional), so a dashboard can show whose team it is."""
        teams = self._options[CONF_TEAMS]
        if user_input is not None:
            self._options[CONF_PERSONS] = {team["id"]: user_input[team["name"]] for team in teams if user_input.get(team["name"])}
            return self.async_create_entry(data=self._options)

        persons = self._current.get(CONF_PERSONS, {})
        schema: dict[Any, Any] = {}
        for team in teams:
            # The form shows the key as the label, so the key is the name of the team
            key = vol.Optional(team["name"], description={"suggested_value": persons.get(team["id"])})
            schema[key] = selector.EntitySelector(selector.EntitySelectorConfig(domain="person"))
        return self.async_show_form(
            step_id="persons",
            data_schema=vol.Schema(schema),
            description_placeholders={"teams": ", ".join(team["name"] for team in teams)},
        )
