# Local BookMyShow monitor - direct requests

## Files to update
1. Replace the project's `fetcher.py` with the supplied `fetcher.py`.
2. Apply the exact `fetch_showtimes()` replacement in `main_config_changes.txt`.
3. Apply the two-line timeout change to `config.py`.
4. Leave `state_store.py` and all Gmail email code unchanged.

## State file
Create `state/state.json` with valid JSON (not a zero-byte file):

{
  "version": 1,
  "profiles": {}
}

The monitor uses `state/state.json` relative to the project working directory.
Always launch it from the project root.

## .env
Keep the existing Gmail settings:
- BMS_EMAIL_SENDER
- BMS_EMAIL_RECIPIENTS
- BMS_GMAIL_APP_PASSWORD

Remove SCRAPERAPI_API_KEY if it is no longer used.

Optional direct-request cooldown settings:
- BMS_403_COOLDOWN_SECONDS=240
- BMS_403_MAX_RETRIES=1

## Install and run (Windows PowerShell)
From the project root:

    py -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install -r requirements.txt
    python main.py

If the virtual environment already exists, activate it and run only the install/run commands.

## What the fetcher does
- Calls the same BMS API URL and query parameters already assembled by main.py.
- Does not call ScraperAPI.
- On HTTP 403, waits 240 seconds and retries once.
- On network errors and 5xx responses, performs short bounded retries.
- On HTTP 429, honours Retry-After when supplied.
- Returns only a JSON object; main.py still performs date/venue validation
  before any state update.

## Important testing note
A successful HTTP 200 is not enough. Confirm that main.py reports the
requested date and venue as validated. If BMS returns a different date,
the existing validation must reject it and preserve that scope's prior state.

This is a single monitor execution. To run every 10 minutes, use Windows
Task Scheduler after the one-run test succeeds. Do not run two copies
concurrently against the same state.json.


commands:
cd "E:\To Learn\Pet-Project-Latest\random-rhapshody"
.\tools\nssm.exe restart BMSMonitor