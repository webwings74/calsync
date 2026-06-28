#!/usr/bin/env python3
"""
CalSync - Synology Calendar
Downloadt een ICS-vliegrooster en importeert het in de Synology-agenda.
Reisverlof-dagen worden uitgefilterd.

Gebruik: python3 calsync.py
Configuratie: config.py (zie config-example.py)
"""

import urllib.request
import subprocess
import tempfile
import os
import sys
import logging
from datetime import datetime

import config

# SUMMARY-waarden die worden overgeslagen (hoofdletterongevoelig)
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


# ── Functies ──────────────────────────────────────────────────────────────────

def download_ics(url: str) -> str:
    log.info(f"Downloaden: {url}")
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            content = resp.read().decode("utf-8")
        log.info(f"Ontvangen: {len(content):,} bytes")
        return content
    except Exception as e:
        log.error(f"Download mislukt: {e}")
        raise


def filter_events(ics_content: str) -> str:
    """
    Verwijdert VEVENT-blokken waarvan de SUMMARY een waarde uit
    SKIP_SUMMARIES bevat. De rest van de kalender blijft intact.
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

    log.info(f"Filter: {kept} events behouden, {skipped} overgeslagen (Reisverlof)")
    return "\n".join(result)


def import_to_calendar(ics_content: str) -> None:
    """
    Schrijft het gefilterde ICS naar een tijdelijk bestand en importeert
    het via DAViCal's load_calendar.php als synocalendar-gebruiker.
    Gebruikt 'replace' zodat verwijderde of gewijzigde vluchten bijgewerkt worden.
    """
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".ics", delete=False, encoding="utf-8"
    )
    try:
        tmp.write(ics_content)
        tmp.close()
        os.chmod(tmp.name, 0o644)

        log.info(f"Importeren naar kalender: {config.CAL_PATH}")
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
            log.info("Import geslaagd ✓")
        else:
            log.error(f"Import mislukt: {output}")
            sys.exit(1)

    finally:
        os.unlink(tmp.name)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("=" * 50)
    log.info("CalSync gestart")
    log.info("=" * 50)

    try:
        ics      = download_ics(config.ICS_URL)
        filtered = filter_events(ics)
        import_to_calendar(filtered)
        log.info("Sync voltooid ✓")
    except Exception as e:
        log.error(f"Sync mislukt: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
