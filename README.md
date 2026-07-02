# CalSync

Syncs an ICS flight roster to a Synology Calendar (DAViCal). Travel leave entries are automatically filtered out before import.

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
