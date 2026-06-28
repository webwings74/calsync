#!/usr/bin/env python3
"""
CalSync - Synology Calendar
Downloads an ICS flight roster and imports it into the Synology calendar.
Travel leave days are filtered out.

Usage: python3 calsync.py
Configuration: config.py (see config-example.py)
"""

import urllib.request
import subprocess
import tempfile
import os
import sys
import logging

import config

# SUMMARY values to skip (case-insensitive)
SKIP_SUMMARIES = ["reisverlof"]

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ── Functions ─────────────────────────────────────────────────────────────────

def download_ics(url: str) -> str:
    log.info(f"Downloading: {url}")
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            content = resp.read().decode("utf-8")
        log.info(f"Received: {len(content):,} bytes")
        return content
    except Exception as e:
        log.error(f"Download failed: {e}")
        raise


def filter_events(ics_content: str) -> str:
    """
    Removes VEVENT blocks whose SUMMARY contains a value from
    SKIP_SUMMARIES. The rest of the calendar is left intact.
    """
    lines = ics_content.splitlines()
    result = []
    in_event = False
    event_lines = []
    skip_event = False
    kept = skipped = 0

    for line in lines:
        stripped = line.strip()

        if stripped == "BEGIN:VEVENT":
            in_event = True
            event_lines = [line]
            skip_event = False

        elif stripped == "END:VEVENT":
            event_lines.append(line)
            if skip_event:
                skipped += 1
            else:
                result.extend(event_lines)
                kept += 1
            in_event = False
            event_lines = []

        elif in_event:
            event_lines.append(line)
            if stripped.upper().startswith("SUMMARY:"):
                summary = stripped[8:].lower()
                if any(s in summary for s in SKIP_SUMMARIES):
                    skip_event = True

        else:
            result.append(line)

    log.info(f"Filter: {kept} events kept, {skipped} skipped (travel leave)")
    return "\n".join(result)


def import_to_calendar(ics_content: str) -> None:
    """
    Writes the filtered ICS to a temp file and imports it via
    DAViCal's load_calendar.php as the synocalendar user.
    Uses 'replace' so deleted or changed flights are updated.
    """
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".ics", delete=False, encoding="utf-8"
    )
    try:
        tmp.write(ics_content)
        tmp.close()
        os.chmod(tmp.name, 0o644)

        log.info(f"Importing into calendar: {config.CAL_PATH}")
        result = subprocess.run(
            [
                "sudo", "-u", "synocalendar",
                config.PHP_BIN, config.LOAD_SCRIPT,
                "localhost", "replace", config.CAL_PATH, tmp.name,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        output = (result.stdout + result.stderr).strip()
        if "was loaded from file" in output:
            log.info("Import successful ✓")
        else:
            log.error(f"Import failed: {output}")
            sys.exit(1)

    finally:
        os.unlink(tmp.name)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("=" * 50)
    log.info("CalSync started")
    log.info("=" * 50)

    try:
        ics      = download_ics(config.ICS_URL)
        filtered = filter_events(ics)
        import_to_calendar(filtered)
        log.info("Sync completed ✓")
    except Exception as e:
        log.error(f"Sync failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
