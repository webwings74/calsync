#!/usr/bin/env python3
"""
CalSync - family roster
Downloads the ICS flight roster from config.ICS_URL and turns it into a
simple calendar for the family: one event per duty, from check-in
("aanmelden") to check-out ("afmelden"). Multi-day trips with night stops
become a single event. Everything else (leave, holidays, simulator, ...)
is left out.

Writes family-roster.ics and prints an overview.

Usage:
  python3 family-roster.py              # duties from today onwards
  python3 family-roster.py --all        # include past duties
  python3 family-roster.py -o out.ics   # different output file
"""

import argparse
import base64
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urljoin

import config

LOCATION = "P30 Personeelsparkeerterrein"

# Known places, matched against the original roster title (case-insensitive).
# lat/lon give Apple Calendar an exact map pin (via X-APPLE-STRUCTURED-LOCATION).
PLACES = {
    "spl-oost": {
        "name": "SPL-Oost",
        "address": "Behoudenvaartweg, 1117 EL Luchthaven Schiphol",
        "lat": 52.308478, "lon": 4.803679,
    },
}
HOME = "AMS"
DAYS_NL = ["ma", "di", "wo", "do", "vr", "za", "zo"]

FLIGHT_RE = re.compile(r"^(DH/\s*)?(KL\d+)\s+([A-Z]{3})-([A-Z]{3})")
NIGHTSTOP_RE = re.compile(r"^Nachtstop\s+([A-Z]{3})")
# Simulator / training sessions, shown as "Richard: Simulator"
SIM_RE = re.compile(r"\b(loe check|fcl check|type recurrent)\b", re.IGNORECASE)


# ── Reading the roster ────────────────────────────────────────────────────────

def download(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read().decode("utf-8")


def unfold(raw: str) -> list:
    """RFC 5545: lines starting with a space or tab continue the previous line."""
    lines = []
    for line in raw.splitlines():
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def parse_dt(value: str):
    """Returns (naive local datetime, all_day). UTC times are converted to local."""
    v = value.strip()
    if len(v) == 8:
        return datetime.strptime(v, "%Y%m%d"), True
    if v.endswith("Z"):
        dt = datetime.strptime(v, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return dt.astimezone().replace(tzinfo=None), False
    return datetime.strptime(v, "%Y%m%dT%H%M%S"), False


def unescape(text: str) -> str:
    return (text.replace("\\n", " | ").replace("\\N", " | ")
                .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\"))


def parse_events(raw: str) -> list:
    events, ev = [], None
    for line in unfold(raw):
        if line == "BEGIN:VEVENT":
            ev = {}
        elif line == "END:VEVENT" and ev is not None:
            if "start" in ev:
                ev.setdefault("end", ev["start"])
                events.append(ev)
            ev = None
        elif ev is not None and ":" in line:
            prop, value = line.split(":", 1)
            name = prop.split(";", 1)[0].upper()
            try:
                if name == "DTSTART":
                    ev["start"], ev["all_day"] = parse_dt(value)
                elif name == "DTEND":
                    ev["end"], _ = parse_dt(value)
            except ValueError:
                pass
            if name == "SUMMARY":
                ev["summary"] = unescape(value).strip()
    events.sort(key=lambda e: e["start"])
    return events


# ── Building duties ───────────────────────────────────────────────────────────

def build_duties(events: list) -> list:
    """
    Groups "Flight day" events into duties. A duty starts at a flight day
    whose title contains "aanmelden" and ends at one containing "afmelden".
    Flights and night stops within that time window are then collected for
    the description (they can be listed after the closing flight day).
    """
    duties, duty = [], None

    # Pass 1: duty windows from the "Flight day" events
    for ev in events:
        low = ev.get("summary", "").lower()
        if not low.startswith("flight day"):
            continue
        if duty is None or "aanmelden" in low:
            # New duty (or the feed starts mid-trip)
            if duty is not None:
                duty["incomplete"] = True
                duties.append(duty)
            duty = {"start": ev["start"], "end": ev["end"], "flights": [],
                    "nightstops": [], "incomplete": "aanmelden" not in low}
        duty["end"] = max(duty["end"], ev["end"])
        if "afmelden" in low:
            duties.append(duty)
            duty = None
    if duty is not None:            # feed ends mid-trip
        duty["incomplete"] = True
        duties.append(duty)

    # Pass 2: assign flights and night stops to their duty
    for ev in events:
        s = ev.get("summary", "")
        d = next((d for d in duties if d["start"] <= ev["start"] < d["end"]), None)
        if d is None:
            continue
        m = FLIGHT_RE.match(s)
        if m:
            d["flights"].append({
                "dh": bool(m.group(1)), "no": m.group(2),
                "from": m.group(3), "to": m.group(4),
                "start": ev["start"], "end": ev["end"],
            })
            continue
        m = NIGHTSTOP_RE.match(s)
        if m:
            d["nightstops"].append({"apt": m.group(1), "start": ev["start"]})

    duties = [dict(d, kind="flight") for d in duties if d["flights"]]

    # Simulator / training sessions become their own events
    for ev in events:
        if SIM_RE.search(ev.get("summary", "")) and not ev.get("all_day"):
            duties.append({"kind": "sim", "start": ev["start"], "end": ev["end"],
                           "summary": ev["summary"], "incomplete": False})

    return sorted(duties, key=lambda d: d["start"])


def destinations(duty: dict) -> list:
    seen = []
    for f in duty["flights"]:
        for apt in (f["from"], f["to"]):
            if apt != HOME and apt not in seen:
                seen.append(apt)
    return seen


def title(duty: dict) -> str:
    return "Richard: Simulator" if duty["kind"] == "sim" else "Richard: Vliegen"


def description(duty: dict) -> list:
    if duty["kind"] == "sim":
        return [f"{duty['start']:%d-%m %H:%M} - {duty['end']:%H:%M}", duty["summary"]]
    lines = [f"Aanmelden {duty['start']:%d-%m %H:%M} - afmelden {duty['end']:%d-%m %H:%M}",
             "Bestemmingen: " + ", ".join(destinations(duty))]
    items = ([(f["start"], 0, f) for f in duty["flights"]] +
             [(n["start"], 1, n) for n in duty["nightstops"]])
    for _, kind, it in sorted(items, key=lambda x: (x[0], x[1])):
        if kind == 1:
            lines.append(f"-- Nachtstop: {it['apt']} --")
            continue
        dh = " (als passagier)" if it["dh"] else ""
        lines.append(f"{it['start']:%d-%m %H:%M}  {it['no']} {it['from']}-{it['to']}{dh}")
    if duty["incomplete"]:
        lines.append("Let op: begin of einde van deze reis valt buiten het rooster.")
    return lines


# ── Writing ICS ───────────────────────────────────────────────────────────────

def ics_escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;")
                .replace(",", "\\,").replace("\n", "\\n"))


def ics_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def fold(line: str) -> str:
    """Folds lines longer than 75 octets (RFC 5545)."""
    out, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > (75 if not out else 74):
            out.append(cur.decode("utf-8"))
            cur = b""
        cur += b
    out.append(cur.decode("utf-8"))
    return "\r\n ".join(out)


HEADER = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//calsync//family-roster//NL",
    "CALSCALE:GREGORIAN",
]
UID_PREFIX = "family-roster-"
COMPARE_KEYS = ("DTSTART", "DTEND", "SUMMARY", "LOCATION", "GEO", "DESCRIPTION", "TRANSP")


def uid(duty: dict) -> str:
    return f"{UID_PREFIX}{ics_utc(duty['start'])}@calsync"


def event_props(duty: dict) -> dict:
    """The properties that define an event; also used to detect changes."""
    props = {
        "DTSTART": ics_utc(duty["start"]),
        "DTEND": ics_utc(duty["end"]),
        "SUMMARY": ics_escape(title(duty)),
        "DESCRIPTION": ics_escape("\n".join(description(duty))),
        "TRANSP": "TRANSPARENT",
    }
    if duty["kind"] == "flight":
        props["LOCATION"] = ics_escape(LOCATION)
    else:
        place = find_place(duty.get("summary", ""))
        if place:
            props["LOCATION"] = ics_escape(f"{place['name']}\n{place['address']}")
            props["GEO"] = f"{place['lat']};{place['lon']}"
            key = ("X-APPLE-STRUCTURED-LOCATION;VALUE=URI;"
                   f"X-ADDRESS=\"{place['address']}\";X-APPLE-RADIUS=50;"
                   f"X-TITLE=\"{place['name']}\"")
            props[key] = f"geo:{place['lat']},{place['lon']}"
    return props


def find_place(text: str):
    low = text.lower()
    return next((p for k, p in PLACES.items() if k in low), None)


def vevent_lines(duty: dict, stamp: str) -> list:
    lines = ["BEGIN:VEVENT", f"UID:{uid(duty)}", f"DTSTAMP:{stamp}"]
    lines += [f"{k}:{v}" for k, v in event_props(duty).items()]
    lines.append("END:VEVENT")
    return lines


def to_ics(lines: list) -> str:
    return "\r\n".join(fold(l) for l in lines) + "\r\n"


def write_ics(duties: list, path: Path) -> None:
    stamp = ics_utc(datetime.now())
    lines = HEADER + ["X-WR-CALNAME:Rooster (familie)"]
    for d in duties:
        lines += vevent_lines(d, stamp)
    lines.append("END:VCALENDAR")
    path.write_text(to_ics(lines), encoding="utf-8")


# ── iCloud (CalDAV) ───────────────────────────────────────────────────────────

ICLOUD_URL = "https://caldav.icloud.com/"
NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav"}


class CalDAV:
    def __init__(self, user: str, password: str):
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.auth = f"Basic {token}"

    def request(self, method: str, url: str, body: str = None, headers: dict = None):
        h = {"Authorization": self.auth}
        if body is not None:
            h["Content-Type"] = "application/xml; charset=utf-8"
        h.update(headers or {})
        req = urllib.request.Request(url, data=body.encode("utf-8") if body else None,
                                     headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 401:
                sys.exit("iCloud: login refused - check ICLOUD_USER / ICLOUD_APP_PASSWORD")
            raise RuntimeError(f"iCloud {method} {url}: HTTP {e.code} {e.reason}") from None

    def propfind(self, url: str, props: str, depth: str = "0"):
        body = (f'<?xml version="1.0" encoding="utf-8"?>'
                f'<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                f'<d:prop>{props}</d:prop></d:propfind>')
        _, text = self.request("PROPFIND", url, body, {"Depth": depth})
        return ET.fromstring(text)

    def find_calendar(self, name: str) -> str:
        root = self.propfind(ICLOUD_URL, "<d:current-user-principal/>")
        principal = urljoin(ICLOUD_URL, root.find(".//d:current-user-principal/d:href", NS).text)

        root = self.propfind(principal, "<c:calendar-home-set/>")
        home = urljoin(principal, root.find(".//c:calendar-home-set/d:href", NS).text)

        root = self.propfind(home, "<d:displayname/><d:resourcetype/>", depth="1")
        names = []
        for r in root.findall("d:response", NS):
            if r.find(".//d:resourcetype/c:calendar", NS) is None:
                continue
            dn = r.find(".//d:displayname", NS)
            dn = dn.text if dn is not None else ""
            names.append(dn)
            if dn == name:
                return urljoin(home, r.find("d:href", NS).text)
        sys.exit(f"iCloud: calendar '{name}' not found. Available: {', '.join(names)}")

    def list_events(self, cal_url: str) -> dict:
        """Returns {uid: {"href", "etag", "props"}} for events created by this script."""
        body = ('<?xml version="1.0" encoding="utf-8"?>'
                '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                '<d:prop><d:getetag/><c:calendar-data/></d:prop>'
                '<c:filter><c:comp-filter name="VCALENDAR">'
                '<c:comp-filter name="VEVENT"/></c:comp-filter></c:filter>'
                '</c:calendar-query>')
        _, text = self.request("REPORT", cal_url, body, {"Depth": "1"})
        found = {}
        for r in ET.fromstring(text).findall("d:response", NS):
            data = r.find(".//c:calendar-data", NS)
            if data is None or not data.text:
                continue
            props = {}
            for line in unfold(data.text):
                if ":" in line:
                    k, v = line.split(":", 1)
                    props.setdefault(k.split(";", 1)[0].upper(), v)
            u = props.get("UID", "")
            if not u.startswith(UID_PREFIX):
                continue        # never touch events this script didn't create
            etag = r.find(".//d:getetag", NS)
            found[u] = {"href": urljoin(cal_url, r.find("d:href", NS).text),
                        "etag": etag.text if etag is not None else None,
                        "props": props}
        return found

    def put(self, url: str, ics: str, etag: str = None) -> None:
        h = {"Content-Type": "text/calendar; charset=utf-8"}
        h.update({"If-Match": etag} if etag else {"If-None-Match": "*"})
        self.request("PUT", url, ics, h)

    def delete(self, url: str, etag: str = None) -> None:
        self.request("DELETE", url, None, {"If-Match": etag} if etag else {})


def sync_icloud(duties: list, dry_run: bool) -> None:
    for key in ("ICLOUD_USER", "ICLOUD_APP_PASSWORD", "ICLOUD_CALENDAR"):
        if not getattr(config, key, None):
            sys.exit(f"{key} missing in config.py (see config-example.py)")

    dav = CalDAV(config.ICLOUD_USER, config.ICLOUD_APP_PASSWORD)
    cal_url = dav.find_calendar(config.ICLOUD_CALENDAR)
    existing = dav.list_events(cal_url)
    now = datetime.now()
    stamp = ics_utc(now)
    wanted = {uid(d): d for d in duties}
    added = updated = deleted = unchanged = 0
    prefix = "[dry-run] " if dry_run else ""

    for u, d in wanted.items():
        ics = to_ics(HEADER + vevent_lines(d, stamp) + ["END:VCALENDAR"])
        old = existing.get(u)
        if old is None:
            print(f"{prefix}+ nieuw:    {d['start']:%d-%m %H:%M}  {title(d)}")
            if not dry_run:
                dav.put(urljoin(cal_url, quote(u) + ".ics"), ics)
            added += 1
        elif any(old["props"].get(k, "") != event_props(d).get(k, "") for k in COMPARE_KEYS):
            print(f"{prefix}~ gewijzigd: {d['start']:%d-%m %H:%M}  {title(d)}")
            if not dry_run:
                dav.put(old["href"], ics, old["etag"])
            updated += 1
        else:
            unchanged += 1

    # Remove duties that disappeared from the roster; past events are kept.
    for u, old in existing.items():
        if u in wanted:
            continue
        try:
            end = datetime.strptime(old["props"].get("DTEND", ""), "%Y%m%dT%H%M%SZ")
            end = end.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        except ValueError:
            continue
        if end <= now:
            continue
        print(f"{prefix}- vervallen: {u}")
        if not dry_run:
            dav.delete(old["href"], old["etag"])
        deleted += 1

    print(f"\n{prefix}iCloud '{config.ICLOUD_CALENDAR}': {added} nieuw, {updated} gewijzigd, "
          f"{deleted} verwijderd, {unchanged} ongewijzigd")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Build a simple family calendar from the flight roster.")
    p.add_argument("--all", action="store_true", help="include duties in the past")
    p.add_argument("-o", "--output", default=str(Path(__file__).with_name("family-roster.ics")),
                   help="output ICS file (default: family-roster.ics next to this script)")
    p.add_argument("--upload", action="store_true",
                   help="sync the duties to the iCloud calendar set in config.py")
    p.add_argument("--dry-run", action="store_true",
                   help="with --upload: only show what would change in iCloud")
    p.add_argument("-q", "--quiet", action="store_true", help="don't print the duty overview")
    args = p.parse_args()

    try:
        events = parse_events(download(config.ICS_URL))
    except Exception as e:
        sys.exit(f"Could not load roster: {e}")

    duties = build_duties(events)
    if not args.all:
        now = datetime.now()
        duties = [d for d in duties if d["end"] > now]

    write_ics(duties, Path(args.output))
    print(f"{len(duties)} diensten → {args.output}\n")

    if not args.quiet:
        for d in duties:
            s, e = d["start"], d["end"]
            end = f"{e:%H:%M}" if s.date() == e.date() else f"{DAYS_NL[e.weekday()]} {e:%d-%m %H:%M}"
            flag = "  (onvolledig)" if d["incomplete"] else ""
            print(f"{DAYS_NL[s.weekday()]} {s:%d-%m %H:%M} → {end:15} {title(d)}{flag}")
            for line in description(d)[1:]:
                print(f"{'':34}{line}")
            print()

    if args.upload:
        try:
            sync_icloud(duties, args.dry_run)
        except RuntimeError as e:
            sys.exit(str(e))


if __name__ == "__main__":
    main()
