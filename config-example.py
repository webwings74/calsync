# Copy this file to config.py and fill in your own values.
ICS_URL     = "https://example.com/your-roster.ics"   # personal ICS URL of your flight roster
CAL_PATH    = "/username/calendar-id/"                 # DAViCal calendar path
PHP_BIN     = "/usr/local/bin/php74"                   # path to PHP binary on the NAS
LOAD_SCRIPT = "/volume1/@appstore/Calendar/davical/scripts/load_calendar.php"
LOG_FILE    = "/volume1/Projects/calsync.log"

# family-roster.py --upload: iCloud calendar to sync the family roster to
ICLOUD_USER         = "you@icloud.com"          # Apple ID
ICLOUD_APP_PASSWORD = "xxxx-xxxx-xxxx-xxxx"     # app-specific password (account.apple.com)
ICLOUD_CALENDAR     = "Familie"                 # exact name of the (shared) iCloud calendar
