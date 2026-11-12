# CalSync

<img src="https://upload.wikimedia.org/wikipedia/commons/c/c7/KLM_logo.svg" alt="KLM logo" height="60" align="right">

A Python script, that can be automatically run via the Task Planner of a Synology NAS, like a DS718+. 
It Syncs an KLM ICS flight roster to a Synology Calendar (DAViCal).
Travel leave entries are automatically filtered out before import.

## How it works

1. Downloads an `.ics` file from a configured URL
2. Strips any events whose `SUMMARY` matches a skip list (default: `reisverlof`)
3. Imports the filtered calendar via DAViCal's `load_calendar.php` using `replace` mode, so deleted or changed flights are kept in sync

## Requirements

- Python 3
- Synology NAS with the Calendar package installed (DAViCal)
- PHP available on the NAS (e.g. `/usr/local/bin/php74`)
- `sudo` access to run as the `synocalendar` system user

## Setup

1. Clone the repository on your Synology NAS:
   ```bash
   git clone https://github.com/webwings74/calsync.git /volume1/Projects/calsync
   ```

2. Copy the example config and fill in your values:
   ```bash
   cp config-example.py config.py
   nano config.py
   ```

3. Run manually to verify:
   ```bash
   python3 calsync.py
   ```

## Family roster

`family-roster.py` builds a simplified calendar for the family from the same
ICS feed: one event per duty, from check-in (`aanmelden`) to check-out
(`afmelden`). A multi-day trip with night stops becomes a single event, titled
`Richard: Vliegen`, located at `P30 Personeelsparkeerterrein`, with the
destinations, flights and night stops listed in the description. Leave, holidays and other non-flight items are left out.

```bash
python3 family-roster.py              # duties from today onwards
python3 family-roster.py --all        # include past duties
python3 family-roster.py -o out.ics   # different output file
```

### Syncing to a shared iCloud calendar

With `--upload` the duties are written straight into an iCloud calendar via
CalDAV, so it can be shared with the family the normal iCloud way — no public
URL needed. Create an app-specific password at account.apple.com and add
`ICLOUD_USER`, `ICLOUD_APP_PASSWORD` and `ICLOUD_CALENDAR` to `config.py`.

```bash
python3 family-roster.py --upload --dry-run   # show what would change
python3 family-roster.py --upload -q          # sync (e.g. daily via Task Scheduler)
```

New duties are added, changed ones updated and duties that disappeared from
the roster are removed. Only events created by this script (UID starting with
`family-roster-`) are ever touched, and past events are left alone.

Output is written to `family-roster.ics` (excluded from git). Each event has a
stable UID based on its check-in time, so re-importing updates existing events.

## Configuration (`config.py`)

| Variable | Description |
|----------|-------------|
| `ICS_URL` | Personal ICS URL of your flight roster |
| `CAL_PATH` | DAViCal calendar path (e.g. `/username/calendar-id/`) |
| `PHP_BIN` | Path to the PHP binary on the NAS |
| `LOAD_SCRIPT` | Path to DAViCal's `load_calendar.php` |
| `LOG_FILE` | Path for the log file |

`config.py` is excluded from version control via `.gitignore`.

## Scheduling on Synology

Schedule the script in Synology Task Scheduler:
- **Task type**: User-defined script
- **User**: `root`
- **Schedule**: e.g. daily at 04:00
- **Command**:
  ```bash
  python3 /volume1/Projects/calsync/calsync.py
  ```

## License

Licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE). You may use, modify, and distribute this code for any noncommercial purpose.
