# jobscraper

**jobscraper** searches job sites for you and saves the results in a spreadsheet you can open in
Excel, Google Sheets, LibreOffice or Numbers.

For every job it finds, the spreadsheet has:

| Column | What it contains |
|---|---|
| `title`, `company`, `location` | The basics |
| `remote` | `Remote`, `Hybrid`, `On-site` or `Unknown` |
| `url` | A link to the job posting (clickable in Excel) |
| `posted_date` | When the job was posted (`YYYY-MM-DD`) |
| `summary` | A short description of the job |
| `education` | Degrees mentioned, e.g. `Bachelor's (or equivalent experience)` |
| `certifications` | Certifications mentioned, e.g. `CISSP; CompTIA Security+; OSCP` |
| `experience` | Years of experience asked for, e.g. `3+ years` |
| `clearance` | Security clearances, e.g. `TS/SCI; Polygraph` |
| `requirements` | The requirement bullet points, separated by ` \| ` |
| `source`, `employment_type`, `salary`, `tags` | Extra details when the site provides them |

You can search by **field** (e.g. cybersecurity), **keywords**, **remote only**, **location**,
**how recently the job was posted**, and choose **which websites / domains** to search.

---

## Contents

1. [Installation (step by step)](#1-installation-step-by-step)
2. [Your first search](#2-your-first-search)
3. [Choosing what to search for](#3-choosing-what-to-search-for)
4. [Choosing which sites to search](#4-choosing-which-sites-to-search)
5. [Saving results (CSV, Excel, ...)](#5-saving-results-csv-excel-)
6. [Recipes](#6-recipes)
7. [All options](#7-all-options)
8. [Troubleshooting](#8-troubleshooting)
9. [Being a good web citizen](#9-being-a-good-web-citizen)
10. [For developers](#10-for-developers)

---

## 1. Installation (step by step)

You only need to do this once.

### Step 1 – Install Python

jobscraper needs **Python 3.9 or newer**.

* **Windows:** download Python from <https://www.python.org/downloads/>. When the installer starts,
  **tick the box "Add python.exe to PATH"** before clicking *Install Now*.
* **macOS:** download it from <https://www.python.org/downloads/>, or with Homebrew run `brew install python`.
* **Linux:** Python is usually already installed. If not: `sudo apt install python3 python3-venv python3-pip`
  (Debian/Ubuntu) or `sudo dnf install python3` (Fedora).

### Step 2 – Open a terminal

All the commands below are typed into a terminal (also called a command prompt), then you press **Enter**.

* **Windows:** press the Windows key, type `PowerShell`, and open *Windows PowerShell*.
* **macOS:** press `Cmd + Space`, type `Terminal`, and press Enter.
* **Linux:** open the *Terminal* app.

Check that Python works:

```bash
python --version
```

You should see something like `Python 3.12.3`. If you get "command not found", try `python3 --version`
instead – and use `python3` everywhere this guide says `python`.

### Step 3 – Download jobscraper

**Option A – with Git** (if you have it installed):

```bash
git clone https://github.com/gladiola/jobscraper.git
cd jobscraper
```

**Option B – without Git:** on the GitHub page click the green **Code** button → **Download ZIP**,
unzip it, then in the terminal go into the unzipped folder, for example:

```bash
cd Downloads/jobscraper-main
```

### Step 4 – Create a virtual environment (recommended)

A virtual environment keeps jobscraper's add-ons separate from the rest of your computer.

```bash
python -m venv .venv
```

Then **activate** it:

* Windows (PowerShell): `.venv\Scripts\Activate.ps1`
  * If you get an error about scripts being disabled, run
    `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, answer `Y`, then try again.
* macOS / Linux: `source .venv/bin/activate`

Your prompt now starts with `(.venv)`. **Each time you open a new terminal** to use jobscraper, `cd` into
the jobscraper folder and run the activate command again.

### Step 5 – Install jobscraper

```bash
pip install .
```

### Step 6 – Check it works

```bash
jobscraper --help
```

You should see the list of options. 🎉 You're ready.

> Tip: `python -m jobscraper ...` works everywhere `jobscraper ...` does.

---

## 2. Your first search

Find remote cybersecurity jobs and save them to an Excel file:

```bash
jobscraper --field cybersecurity --remote -o jobs.xlsx
```

When it finishes you'll see something like:

```
Wrote 57 job(s) to jobs.xlsx (xlsx)
```

Open `jobs.xlsx` from the jobscraper folder with Excel (or upload it to Google Sheets). Click a link in
the `url` column to open the job posting.

Searches take a little while (usually under a minute) because jobscraper deliberately waits between
requests so it doesn't overload the websites.

---

## 3. Choosing what to search for

| You want… | Use | Example |
|---|---|---|
| A whole field (uses many related terms) | `--field` | `--field cybersecurity` |
| Jobs mentioning a word or phrase | `-k` / `--keyword` | `-k "cloud security" -k devsecops` |
| Jobs that mention **all** of some terms | `--require` | `--require "full-time"` |
| To leave out jobs mentioning a term | `--exclude` | `--exclude senior --exclude manager` |
| Only look at the job **title** for the above | `--title-only` | |
| Remote jobs only | `--remote` | |
| Remote **or** hybrid | `--remote --include-hybrid` | |
| Jobs in a location | `--location` | `--location "United States"` |
| Jobs posted recently | `--posted-within DAYS` | `--posted-within 5` (last 5 days) |
| At most N results | `--limit N` | `--limit 50` |

Notes:

* Options marked "repeatable" can be given more than once: `-k soc -k "incident response"` finds
  jobs mentioning *either* term.
* Matching ignores upper/lower case, and spaces and hyphens are flexible: `-k "cyber security"` also
  matches "cybersecurity" and "cyber-security".
* Fields available: `cybersecurity`, `software-engineering`, `data`, `devops`, `it-support`.
  See the exact terms with `jobscraper --list-fields`.
* `--posted-within` drops jobs whose posting date is unknown. Add `--include-undated` to keep them.

---

## 4. Choosing which sites to search

### Built-in job boards

See them with `jobscraper --list-sources`.

| Name | Website | Notes |
|---|---|---|
| `remoteok` | remoteok.com | Remote jobs. **Searched by default.** |
| `remotive` | remotive.com | Remote jobs. **Searched by default.** |
| `arbeitnow` | arbeitnow.com | Europe & remote. **Searched by default.** |
| `ninjajobs` | ninjajobs.org | Vetted cybersecurity jobs. Add with `--source ninjajobs`. |
| `linkedin` | linkedin.com | Public LinkedIn job search. Add with `--source linkedin`. See the note below. |

If you don't pick any sites, the three default boards are searched. Pick specific ones with `--source`
(by name or domain), or everything with `--source all`:

```bash
jobscraper --field cybersecurity --source ninjajobs --source linkedin -o jobs.xlsx
```

### Any website / domain you choose: `--site`

Give jobscraper a domain or a careers-page link and it will find the jobs there:

```bash
jobscraper --site example.com --field cybersecurity -o jobs.csv
jobscraper --site https://www.example.com/about/careers -o jobs.csv
```

How it works:

* For a bare domain (`example.com`) it tries `https://example.com/`, `/careers` and `/jobs`.
* It reads the standard job data most career sites publish for Google (schema.org `JobPosting`).
* It follows links that look like job pages on the same site (`/job/...`, `/careers/...`, `/positions/...`).
* If the careers page links to a **Workday**, **Greenhouse** or **Lever** job board, it uses that board directly.
* Pages without structured data are still read on a best-effort basis (title + description).
* It always obeys the site's `robots.txt` rules.
* `--max-pages` (default 25) limits how many pages it reads per site.

Have many sites? Put them in a text file, one per line (lines starting with `#` are ignored):

```text
# my-sites.txt
example.com
https://careers.another-company.com/jobs
https://acme.wd5.myworkdayjobs.com/External
https://jobs.lever.co/somecompany
```

```bash
jobscraper --sites-file my-sites.txt --field cybersecurity -o jobs.xlsx
```

### Company job boards (Workday, Greenhouse, Lever)

Many companies host their jobs on one of these systems. Look at the address of the company's job page:

| If the job page address looks like… | Use |
|---|---|
| `https://acme.wd5.myworkdayjobs.com/External` | `--workday https://acme.wd5.myworkdayjobs.com/External` |
| `https://boards.greenhouse.io/acme` | `--greenhouse acme` |
| `https://jobs.lever.co/acme` | `--lever acme` |

(You can also simply pass any of these addresses to `--site`; it recognises them.)

For Workday the address must include the site name after the domain (the `External` part above) – copy
it from your browser's address bar while viewing the company's job list.

### Keeping or removing results by domain

* `--domain example.com` keeps only jobs whose link is on example.com (or a subdomain like jobs.example.com).
* `--exclude-domain example.com` removes them.

### A note on LinkedIn

LinkedIn is supported through its public, logged-out job search, but:

* It is **opt-in** (`--source linkedin`) and is never searched by default.
* LinkedIn's User Agreement restricts automated access – **make sure your use is allowed** before using it.
* LinkedIn blocks rapid requests ("HTTP 429"). jobscraper stops politely when that happens and keeps
  what it already found. Use `--limit`, keep `--delay` at 1 second or more, and avoid running it repeatedly.
* `--remote`, `--location` and `--posted-within` are sent to LinkedIn's own search filters.

---

## 5. Saving results (CSV, Excel, ...)

Choose the file with `-o` / `--output`. The format comes from the file extension:

| Extension | Format | Open with |
|---|---|---|
| `.csv` (default: `jobs.csv`) | Comma-separated | Excel, Google Sheets, LibreOffice, Numbers |
| `.xlsx` | Excel workbook (clickable links, filters, frozen header) | Excel, Google Sheets, LibreOffice |
| `.tsv` | Tab-separated | Spreadsheets, text tools |
| `.json` | JSON | Programs/scripts |

* Use `-f`/`--format` to force a format regardless of the file name.
* Use `-o -` to print CSV/TSV/JSON to the screen instead of a file.
* Add `--include-description` to include each job's full description text as an extra column.
* Running the same command again **overwrites** the file – use a new name to keep old results.

---

## 6. Recipes

```bash
# Remote cybersecurity jobs posted in the last 5 days, as an Excel file
jobscraper --field cybersecurity --remote --posted-within 5 -o recent-cyber.xlsx

# Entry-level SOC / analyst jobs, ignoring senior roles, titles only
jobscraper -k soc -k "security analyst" --exclude senior --exclude lead --title-only -o soc.csv

# Cybersecurity jobs on NinjaJobs and LinkedIn in the United States, remote or hybrid
jobscraper --field cybersecurity --source ninjajobs --source linkedin \
    --location "United States" --remote --include-hybrid --limit 100 -o cyber.xlsx

# All open roles at specific companies
jobscraper --greenhouse gitlab --lever palantir --workday https://acme.wd5.myworkdayjobs.com/External -o companies.xlsx

# Your own list of company websites
jobscraper --sites-file my-sites.txt --field cybersecurity --posted-within 14 -o targets.xlsx

# Remote DevOps jobs that mention Kubernetes
jobscraper --field devops --require kubernetes --remote -o devops.csv
```

> On Windows PowerShell, replace the `\` at the end of a line with a backtick `` ` ``, or put the
> whole command on one line.

---

## 7. All options

Run `jobscraper --help` for the full list. Summary:

| Option | Meaning |
|---|---|
| `-k, --keyword TEXT` | Keep jobs mentioning any of these (repeatable) |
| `--field FIELD` | Keep jobs in a field, using built-in synonyms (repeatable) |
| `--require TEXT` | Keep only jobs mentioning all of these (repeatable) |
| `--exclude TEXT` | Drop jobs mentioning any of these (repeatable) |
| `--title-only` | Match the above against the title only |
| `--remote` / `--include-hybrid` | Remote only / also allow hybrid |
| `--location TEXT` | Location must contain this text (repeatable) |
| `--posted-within DAYS` | Posted in the last DAYS days |
| `--include-undated` | With `--posted-within`, keep jobs with unknown dates |
| `--source NAME` | Built-in board by name/domain, or `all` (repeatable) |
| `--site DOMAIN_OR_URL` (alias `--url`) | Any website, domain or job-board address (repeatable) |
| `--sites-file FILE` | File of domains/URLs, one per line (repeatable) |
| `--greenhouse BOARD` / `--lever COMPANY` / `--workday URL` | Company job boards (repeatable) |
| `--domain` / `--exclude-domain DOMAIN` | Keep / drop jobs by link domain (repeatable) |
| `--max-pages N` | Page limit per site (default 25) |
| `-o, --output FILE` | Output file, `-` for screen (default `jobs.csv`) |
| `-f, --format` | `csv`, `tsv`, `xlsx` or `json` |
| `--include-description` | Add the full description column |
| `--limit N` | Stop after N matching jobs |
| `--delay SECONDS` | Wait between requests to the same site (default 1) |
| `--timeout SECONDS` | Give up on a slow page after this long (default 20) |
| `--user-agent TEXT` | Identify yourself differently to websites |
| `--list-sources` / `--list-fields` | Show built-in boards / fields and exit |
| `-v, --verbose` | Show what it's doing |

---

## 8. Troubleshooting

| Problem | Fix |
|---|---|
| `jobscraper: command not found` / `not recognized` | Activate the virtual environment (Step 4), or use `python -m jobscraper`. |
| `python: command not found` | Use `python3`, or reinstall Python and tick "Add python.exe to PATH" (Windows). |
| `Wrote 0 job(s)` | Your filters may be too strict. Remove `--posted-within`/`--remote`/`--title-only` one at a time, or add `-v` to see what was searched. |
| `WARNING: Source ... failed` | That site was unreachable or changed; the other sites still run. Try again later. |
| `robots.txt disallows ...` | The website asked robots not to read that page, so jobscraper skipped it. |
| LinkedIn `429` warning | LinkedIn is rate-limiting you. Wait a while, use `--limit`, and run it less often. |
| `--site` finds nothing | Open the site in a browser, go to the page listing the jobs, and pass that exact address. If it redirects to Workday/Greenhouse/Lever, pass that address instead. |
| Odd characters (e.g. `Ã©`) in a `.csv` | Use `-o jobs.xlsx` instead, or import the CSV as UTF-8 (in Excel: *Data → From Text/CSV*). |
| `Permission denied` when saving | Close the file in Excel first, then run the command again. |

---

## 9. Being a good web citizen

* jobscraper identifies itself, waits between requests to the same site (`--delay`, default 1 s),
  and obeys `robots.txt` when crawling websites.
* Check each site's terms of use before scraping it, especially LinkedIn.
* Don't lower `--delay` to 0 against real websites, and don't run searches in a tight loop.
* Text in the output comes from other websites. Cells that start with `=`, `+`, `-` or `@` are prefixed
  with `'` so spreadsheet programs won't run them as formulas.

---

## 10. For developers

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
python -m pytest
```

The tests are fully offline (HTTP is mocked).

Code layout (`jobscraper/`):

| File | Purpose |
|---|---|
| `cli.py` | Command-line options and the main search loop |
| `sources.py` | Job sources: RemoteOK, Remotive, Arbeitnow, Greenhouse, Lever, Workday, LinkedIn, NinjaJobs, and the generic website crawler |
| `extract.py` | HTML → text, summaries, remote detection, dates, degree/cert/experience/clearance/requirements extraction |
| `filters.py` | Keyword/field, remote, location, date and domain filters |
| `output.py` | CSV / TSV / XLSX / JSON writers |
| `fetch.py` | HTTP session: User-Agent, timeouts, per-site delay, robots.txt |
| `models.py` | The `Job` record and output column order |

To add a new job board, subclass `Source` in `sources.py`, implement `fetch()` to yield `Job` objects,
and register it in `BUILTIN_SOURCES` (and in `site_source()` if it should be recognised from a URL).
