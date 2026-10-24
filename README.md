# Breeders Cup Automation

[![CI](https://github.com/mevorahde/Breeders_Cup_Automation/actions/workflows/ci.yml/badge.svg)](https://github.com/mevorahde/Breeders_Cup_Automation/actions/workflows/ci.yml)

## First-time setup after cloning

Requires Python 3.11 or newer on Windows.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Copy your reference workbook to `templates/2024 Breeders Cup Final.xlsx`.
The code requires this local file; Excel workbooks are excluded from Git.
See `templates/README.md`. No credentials are needed for the public data sources.

## Normal yearly run

Run from the project directory:

```powershell
.\.venv\Scripts\python.exe -m breeders_cup.cli
```

Equivalent explicit command:

```powershell
.\.venv\Scripts\python.exe -m breeders_cup.cli update
```

The year defaults to the current Los Angeles calendar year. The script creates
`generated` if needed and maintains **one production Excel file per year**:
`generated/Breeders Cup YYYY.xlsx` (for example, `Breeders Cup 2026.xlsx`).
If it does not exist it is created; if it exists its rows are refreshed.
No dated versions, demo versions, backup workbooks or JSON sidecars are created
in `generated` by this normal run. Existing files from earlier workflows are
not deleted automatically.

Research snapshots are kept in `data/state/YYYY.json`, reports in
`data/reports/YYYY.json`, and cached public pedigree pages in `data/cache/pedigree`.
Deleting `generated` will not delete that research. Deleting a workbook does
remove manual picks stored in that workbook; preservation applies when the file
exists during an update.

## Windows batch launcher and Task Scheduler

Double-click `run_breeders_cup.bat`, or run it from a terminal. It always switches
to its own project directory and uses `.venv\Scripts\python.exe`. It performs
the normal current-year update and appends output/errors to
`logs/scheduled-run.log`. Exit code 0 means success; nonzero means failure.
A missing virtual environment returns code 2 with setup instructions in the log.
The launcher does not pause or prompt, so it can run unattended.

### Creating or recreating a task

To create a Windows Task Scheduler task:

1. Open **Task Scheduler** and select **Create Task**.
2. Choose the trigger and frequency you want.
3. Add a **Start a program** action with these settings:

   - Program/script: `cmd.exe`
   - Add arguments: `/d /c ""<repository-folder>\run_breeders_cup.bat""`
   - Start in: `<repository-folder>`

   Replace `<repository-folder>` with the folder where you cloned the repository.

4. Under **Settings**, set **If the task is already running** to
   **Do not start a new instance**. Allow enough runtime for public source lookups.
5. Close the yearly workbook in Excel before the task runs. Check **Last Run
   Result** and the log after the first run. `0x0` means success.

If you move or clone the project elsewhere, change the action's path and
**Start in** folder. The batch file itself needs no path edits. Optional CLI
arguments can follow the batch filename, such as `--year 2026` or
`--template "reference/2024 Breeders Cup Final.xlsx"`.

## GitHub repository contents

Track source code, tests, example data, dependency files, this README, the batch
launcher and `templates/README.md`. `.gitignore` excludes all Excel files, the
local template, `generated`, caches, state, reports, logs, virtual environments
and local settings. `.gitattributes` keeps the Windows launcher in CRLF format.

Ignoring the template does not remove it locally. Every new clone must install
its own reference workbook before running the program or workbook tests.
Research and manual picks are local files; GitHub is not their backup.

### Dependency update pull requests

Dependabot checks Python dependency manifests weekly on Mondays at 9:00 AM
America/Los_Angeles, configured in `.github/dependabot.yml`. Version updates
are grouped into a `python-dependencies` pull request, with at most five open
version-update PRs. Dependabot alerts and security-fix PRs are enabled on GitHub.
Review and merge updates manually; automatic merging is not configured.

GitHub Actions also checks updates to the workflow actions themselves through
Dependabot. Dependency Review runs on pull requests and blocks newly introduced
high or critical vulnerabilities. It can also be started manually with a base
commit SHA for comparison.

## Updating an existing workbook

Race dates are guarded using the current **America/Los_Angeles** calendar date.
When an existing workbook is updated, races dated before today are frozen from
its saved contents. For example, an October 31 run leaves October 30 race rows,
row order, formatting, odds, picks, results and race-summary entries unchanged
while refreshing October 31 races. Today’s races remain live, even if some have
already finished; this guard operates by day rather than individual finish time.
No calendar dates are hardcoded, so the same rule applies in future years.

Past race fields are retained even if the source removes entrants or changes
its historical data. Overage rows for horses entered only in past races are
preserved too. A horse with a current/future engagement can still update in
Overage. Shared column widths may expand to fit current data, and combined
summary totals can recalculate as current-day entries change. The report lists
frozen races under `yearly_update.past_races_preserved`.

If no workbook exists, all available races are generated normally because there
are no saved rows to preserve. Keep the yearly workbook between daily runs.


Hidden horse/race IDs keep picks attached to their horse and race when the
schedule, post positions, row order or horse count changes. Older files without
IDs are migrated by matching horse and race names. The script preserves the Pick
column, its pick colors, entered results and manual results-summary inputs.
Summary formulas are rebuilt for the current row positions. New horses get new
rows. A disappearing source row with a saved pick or result is retained; absence
alone is not treated as a confirmed scratch. An ambiguous identity stops the
update instead of discarding input.

A confirmed scratch sets the Odds cell to `SCR`. A known numeric post is retained.
Explicit official withdrawal notices are also honored. When fresh source data
has no post or odds, the existing value is kept. Final assignment and test modes
cannot silently hide a saved pick or result; such a conflict stops the update.

Updates are prepared in a temporary workbook and replace the original only after
validation. If the workbook changed during processing, the update stops. Close
Excel before running an update so Windows permits replacing the workbook.
The 2024 reference workbook is never modified.

## Workbook content

The script discovers the current-year official race-order announcement on
BreedersCup.com and reads its published schedule tables for track race numbers
and Eastern post times. It matches exact championship names and validates all
14 races before applying a schedule. Numbers are never inferred from row order
or copied from a different year. The source URL and publication date are kept
in the report under `race_schedule`. If retrieval fails, previously verified
same-year race numbers are retained; otherwise unpublished numbers stay pending.

The annual tab follows the current year's schedule, with the Classic on Saturday,
and sorts horses numerically by published post position. Overage is the complete
alphabetical horse registry. Both include ancestry and Other Ancestors matches,
confirmed Cup jockeys when verified, and fitted column widths. Each tab sizes
its columns to its own longest displayed value, allowing widths to shrink as
well as expand. Windows runs use installed desktop Excel's native AutoFit
on a private copy, then apply only the measured widths. Rows remain uniformly
12 points high with wrapping disabled. If Excel is unavailable (including
scheduler sessions where Excel cannot start), measured font widths are used
as a fallback. The annual sheet
ends with the 2024-style RESULTS SUMMARY. DE/H picks and awards are entered by hand.

### Display formatting

All visible cells use **Arial Narrow, 8 point**, retaining the template's bold text
and colors. Column widths are fitted after applying the font.

Both the annual tab and Overage use this visible column order:

BC Race → Post → Result → Odds → Pick → **Date of Birth** → **Name** → Jockey →
Trainer → Color → Last Previous Race → Father → Grandfather(s) →
Great Grandfather(s) → Other Ancestors.

- Horse details display in Title Case, retaining country codes, initials and
  established internal capitals. Picks, scratch codes, source links and hidden
  identities are not title-cased.
- Color labels use **DK Bay** for **Dark Bay or Brown** and **Gray** for
  **Gray or Roan**.
- Last Previous Race keeps the race name and finishing position, removing
  periods and the parenthesized date: `Speakeasy S.: 1 (2026-10-03)` becomes
  `Speakeasy S: 1`.
- Date of Birth remains a real Excel date, displayed as `mm/dd/yyyy`.
- Native Excel AutoFit matches double-clicking a column border. It fits the
  longest entry anywhere in that column on each tab, so shorter entries can
  still have space beside them. There are no width caps or wrapped entries;
  all rows stay at 12 points high.

Existing workbooks with Date of Birth at the end are migrated to the new column
order during refresh, preserving picks, results and the results summary. The
2024 template keeps its original layout.

The nine unique personal famous-ancestor names are in
`src/breeders_cup/famous_horses.py`. Matching normalizes punctuation and country
suffixes and checks collected pedigree tables plus deeper linked parent records.
Source horse IDs, rather than names alone, join those deeper records. Matched
names appear once; evidence paths and URLs are retained in the research snapshot.
No match means no watchlist ancestor was found in available records.

The watchlist is: Mr. Prospector, A.P. Indy, Secretariat, Seattle Slew,
Seeking the Gold, Pleasant Colony, Affirmed, Alydar and Sunday Silence.

The pipeline uses official Breeders' Cup public page data, racedb, netkeiba and
Pedigree Query, with source identity checks and caching. Confirmed jockeys use
official declarations and explicit current-year booking announcements found via
the Sporting Life news sitemap. Last-race riders and projected riders are not
substituted. Sources can be incomplete or blocked; reports record coverage and
unconfirmed riders. Unknown data is not invented.

## Advanced commands

`--year 2026` explicitly chooses a year for `update`. `--cache`, `--template` and
`--generated-dir` can select local paths. Source event-year validation prevents
an old schedule being mistaken for a future one.

Existing `collect-build`, `enrich-build` and `build` commands also update their
selected workbook while preserving picks. Their research/report files now go
under `data`, not beside the workbook. Normal use should use `update` above.

Testing/export commands remain available only when explicitly requested:
`--test` limits displayed fields to 13 while retaining every horse in Overage.
`demo-build --data <research.json> --output <demo.xlsx>` generates labeled
synthetic posts and random odds; demo data cannot update a production workbook.
Do not use demo/test exports for the normal yearly run.

### Demo previews

Choose a preview output outside `generated` to keep it separate from production.
Previews use a saved research snapshot with the current formatting, schedule and
verified horse details. The annual tab contains at most **13 horses per race**;
**Overage** retains every horse in the snapshot. Demo post positions run in order
from 1 within each race; odds are generated sample values. They are not official
draws or odds. Unconfirmed Breeders' Cup jockeys remain blank.

Deleting a preview does not affect production data or manual picks in the
production workbook. Regenerating a preview uses the formatting currently in
the script; a previously created preview does not update itself. Demo creation
does not fetch fresh source data unless a separate collection/update is run.
The `demo-build` CLI also creates `.data.json` and `.report.json` sidecars next
to its chosen output.

## Tests

GitHub Actions runs the public tests on Windows and Linux with Python 3.11 and
3.13 for pull requests and pushes to `main`. Tests use committed fixtures;
they do not scrape live sites or require credentials. Nine workbook integration
tests are explicitly skipped when the private reference template is absent.
Installing the reference template locally enables those tests automatically.
Public CI does not verify the private workbook layout or native Excel AutoFit.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

## License

Licensed under the [MIT License](LICENSE).
