# R.K.H.V. Union Hockey

Home Assistant integration (HACS) for the match schedule of hockey club R.K.H.V. Union (unionhockey.nl, data from Lisa hockey).

## What you get

| Entity | Contents |
|---|---|
| `sensor.union_thuiswedstrijden` | The home matches of the coming days (attribute `matches`: date, time, team, opponent, field, type of field, cancelled). The state is the number of matches. |
| `sensor.union_trainingen` | The outdoor trainings of the coming 14 days (attribute `trainings`). |
| `sensor.union_<team>` | One per followed team. State: start of the next match. Attributes: `next_match`, `matches` (home and away), `results`, `trainings`, the standing (`position`, `points`, `table`, ...) and `person` (who plays in the team). |

## Setup

1. HACS → Custom repositories → add `https://github.com/vinnie1234/R.K.H.V-Union` as *Integration*, download it and restart Home Assistant.
2. Settings → Devices & Services → Add integration → **R.K.H.V. Union Hockey**. The defaults are the ids and key that the website unionhockey.nl itself uses.
3. **Configure**: choose the days ahead, the type of every field (water or artificial grass, used for the cancel advice on the dashboard), and the teams to follow. For a followed team you can link a person (for example a partner who plays in it).

The data is read every 30 minutes (adjustable). Only the home matches are needed to decide about cancelling a match; a followed team also shows its away matches.
