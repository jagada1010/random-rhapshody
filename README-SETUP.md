# BookMyShow Monitor – ScraperAPI version

This package integrates the verified ScraperAPI transport with the BookMyShow response structure and retains the existing Gmail notifications, target filters, cumulative archive, and 10-minute GitHub Actions workflow.

## Files in this package

- `main.py` – monitor, movie/language/date matching, venue-specific premium-format filtering, seat-layout links, email notifications, and awake/sleep behavior.
- `fetcher.py` – sends the BookMyShow API request through ScraperAPI and validates the JSON root.
- `config.py` – profile, dates, active theatre codes, and screen-format rules.
- `state_store.py` – append-only per-profile session archive.
- `.github/workflows/bms-monitor.yml` – 10-minute workflow and persistent `monitor-state` branch.
- `requirements.txt` – Python dependencies.
- `.env.example` – local environment-variable template.

## Install / local run

1. Copy these files into the root of your repository, preserving the `.github/workflows/` path.
2. Create a virtual environment and install dependencies:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and fill in your ScraperAPI key and Gmail settings. Never commit `.env`.
4. Review `config.py`. The supplied default is `SANITY_TEST` (Scene / Telugu / 16 Nov 2026). Switch `ACTIVE_PROFILE` to `REAL_DATA` when you are ready to monitor Avengers: Doomsday (English / 18 and 19 Dec 2026).
5. Run locally:

   ```powershell
   python main.py
   ```

## GitHub Actions setup

Add these repository Actions secrets:

- `SCRAPERAPI_API_KEY`
- `BMS_EMAIL_SENDER`
- `BMS_EMAIL_RECIPIENTS` (comma-separated addresses)
- `BMS_GMAIL_APP_PASSWORD`

Then ensure **Settings → Actions → General → Workflow permissions** allows read and write access to repository contents. Commit the package to the default branch and run **Actions → BookMyShow Monitor → Run workflow**.

The workflow runs every 10 minutes. It stores `state.json` on the separate `monitor-state` branch; do not delete that branch if you want to preserve the archive.

## Filtering behavior

The workflow fetches each unique venue/date once. The response events are read from `ShowDetails[].Event[]` (not `ShowDetails[].Venues.Event`). Each session must match the active profile's movie, language and date, and one of the configured venue-specific format rules:

- AC / ALUC: Dolby Cinema
- PCX / PRHN: PCX Screen
- PCX / PRHN: HDR by Barco
- ART / ACEV: EPIQ
- AAA / ACAS: LED

Only theatre codes in `active_theatres_for_alert` are monitored. Every qualifying session gets a generated BookMyShow seat-layout URL.

## Notification behavior

- Awake window: sends the current matching sessions on every successful 10-minute run when at least one match exists.
- Sleep window: sends at most one email per hour, only when new/reappeared/updated sessions are pending.
- Sleep emails include both the pending changes and the complete cumulative archive.
- The first successful snapshot initializes the archive without creating a false flood of new-session alerts.
- A failed request, invalid JSON, date mismatch, venue mismatch, or missing `Event` list exits with failure before state is updated.
- A valid response with an empty `Event` list is treated as a successful snapshot with no matching shows.

## ScraperAPI usage estimate

With all four theatre codes enabled and two target dates, the monitor makes up to 8 ScraperAPI requests per run (PRHN is fetched once even though it has two format targets). At six runs per hour, that is up to 48 requests per hour or 1,152 per day. Check your ScraperAPI plan/credit allowance before enabling continuous monitoring.

GitHub scheduled runs can be delayed; the 10-minute cron is not an exact real-time guarantee.
