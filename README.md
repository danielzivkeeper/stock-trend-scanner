# Stock Trend Scanner

This is a hobby project. It checks a watchlist of stocks twice every weekday for five patterns that finance research has written about. It gives each stock an explainable 0–10 score and texts you when a score gets high. A dashboard you can install on your phone shows the breakdown and lets you log **fake** trades, so you can test the idea before risking real money.

Everything runs inside one free GitHub repository. You pay nothing for hosting, and your computer doesn't need to be on.

> **Not financial advice.** These are documented *tendencies*, not guarantees. Several of the
> signals are weak or speculative (see the table below). Paper-trade for months before you even
> think about real money.

---

## What's proven and what's speculative

| Signal | Weight | Evidence | Plain-English honesty |
|---|---|---|---|
| **Earnings drift** | 3.0 | **Strong.** Researchers have replicated it many times since Ball & Brown (1968) and Bernard & Thomas (1989). | After a company beats earnings estimates, its stock tends to keep drifting up for weeks. The effect has **shrunk a lot** in large, popular stocks since the 2000s. |
| **Insider buying** | 2.5 | **Moderate to strong.** Seyhun; Lakonishok & Lee (2001); Cohen, Malloy & Pomorski (2012). | Executives buying their own stock with their own money is informative. (Their *selling* isn't.) Treating a "cluster" of buyers as a stronger sign is common practice among traders, but no single study proves that rule. Token buys under $10k are ignored. |
| **Short-squeeze setup** | 2.0 | **Mixed. Read this one.** | On **average**, heavily shorted stocks do **worse** afterward (Asquith, Pathak & Ritter 2005). A squeeze is the rare exception, and this signal only measures the "fuel", never the trigger. It's only useful alongside other signals. The data updates twice a month. |
| **Congress trades** | 1.5 | **Weak / mixed.** | 1990s studies found that members of Congress beat the market. Newer studies mostly don't. Disclosures can arrive up to 45 days late. ⚠️ **The free data mirrors are currently offline** (details below). |
| **Social spike** | 1.0 | **Real but short-lived.** Da, Engelberg & Gao (2011). | A surge in Wikipedia views, Google searches or Reddit mentions tends to push prices up for days to about 2 weeks, then **reverses**. It only counts as confirming evidence. |
| **Chart patterns** | 1.0 | **Mixed.** Lo, Mamaysky & Wang (2000); 52-week highs: George & Hwang (2004). | Scores only **confirmed** breakouts on above-average volume: 52-week high, double bottom, inverse head & shoulders, ascending triangle, cup & handle, bull flag. Patterns that are still "forming" show as 📐 on the card but earn no points. Computer-detected patterns carry *some* information, but most published win rates come from trading books, not research. The 52-week-high part has the best evidence. |
| CEO social activity | — | Not built | Reading X/Twitter now requires a paid API, and scraping it violates X's terms of service. |
| App-store rank jumps | — | Not built | There's no free API for ranking history. |
| Hiring surges | — | Not built | There's no free job-posting API, and scraping job sites violates their terms of service. |

**Speculative design choices** (they're reasonable, but they're guesses, not research): the specific weights, the 5.0 alert threshold, the "2+ insiders" rule, the "full strength at 3× the threshold" scaling, and the 10-day hold period. You can change all of them in `config.json`.

### How the score works

```
score = (sum of  weight × strength  for each signal that fired)  ÷  sum of all weights  × 10
```

- Strength runs from 0 to 1. It's 0.33 when a signal just crosses its threshold and 1.0 at 3× the threshold (for insiders, Congress and social spikes, 1.0 at 2×).
- If a signal **couldn't be checked** (for example, its data source is down), it counts as 0. The total still includes its weight, so missing data can only lower a score, never raise it.
- With the default weights, **no single signal can trigger an alert on its own.** Earnings drift at full strength alone gives 3.0. An alert needs at least two signals agreeing. That's on purpose.
- Every score comes with an explanation that lists which signals fired, why, and the math.

### Known data-source issues (checked October 2026)

- **Congress trades: offline.** Both House/Senate Stock Watcher S3 mirrors return `403 Access Denied`. The signal reports "unavailable" and never makes up data. Until a working source turns up, the best scores possible are 8.5 out of 10. If that bothers you, open `config.json` and set `"congressional_trades": 0` so its weight leaves the total. If you find a working mirror with the same JSON format, paste its URL into `config.json`.
- **Google Trends** (via `pytrends`, an unofficial tool) blocks GitHub's servers almost every time (tested October 2026). The social signal therefore relies on **Wikipedia page views** (official, free, works from anywhere). Google Trends only adds data when you run the scanner on your own computer.
- **Yahoo Finance** (via `yfinance`, also unofficial) occasionally breaks for a day after Yahoo changes its website. The scan logs the error and keeps going.
- **Insider buying** reads Form 4 filings straight from **SEC EDGAR**, the official source. The SEC requires a contact email with automated requests, which goes in the `SEC_CONTACT_EMAIL` secret. Without that secret, the scanner falls back to openinsider.com, a third-party aggregator that does **not** answer GitHub's servers. Purchases under pre-scheduled 10b5-1 plans are ignored, because they aren't conviction buys.
- **Texting:** AT&T **shut down** its email-to-text gateway in 2025, and other carriers may delay or drop these messages. The optional free **ntfy** app (step 5b) is a more reliable backup.

---

## Setup (no command line needed)

You'll do everything on the GitHub website. It takes about 20–30 minutes.

### 1. Make a GitHub account
Go to **https://github.com/signup** and follow the steps. The free plan is all you need.

### 2. Create the repository
1. Once you're logged in, click the **+** in the top-right corner and choose **New repository**.
2. **Repository name:** `stock-trend-scanner`. You can use another name, but it becomes part of your dashboard's web address.
3. Choose **Public**. Free accounts only get GitHub Pages (the dashboard) and unlimited Actions minutes (the scanner) on public repos. Your paper trades **aren't** stored in the repo; they stay on your phone. Your watchlist and scan results **will** be public.
4. Leave everything else as is and click **Create repository**.

### 3. Upload the project files
1. On the new, empty repository page, click the **uploading an existing file** link.
2. On your Mac, open the `stock-trend-scanner` folder in Finder.
3. Press **⌘ Command + ⇧ Shift + . (period)** so Finder shows hidden items. You should now see a faded `.github` folder. **It must be uploaded**, because it holds the scanner's schedule.
4. Select **everything inside** the folder (⌘ Command + A) and drag it onto the GitHub upload page.
5. Wait for all the files to finish listing, then click the green **Commit changes** button at the bottom.
6. Check that it worked: your repo's main page should list a `.github` folder. If it doesn't, see *Troubleshooting* below.

### 4. Get a Gmail "app password" (lets the scanner send texts through your Gmail)
1. Go to **https://myaccount.google.com/security**. Under *How you sign in to Google*, turn on **2-Step Verification** if it isn't already on. Google requires this before it will create app passwords.
2. Go to **https://myaccount.google.com/apppasswords**.
3. Type a name such as `stock scanner` and click **Create**.
4. Copy the 16-letter password Google shows you. You'll paste it in the next step. (Spaces in it are fine.)

> Using a separate, throwaway Gmail account for this is a good idea.

### 5. Add your secrets (private settings the scanner reads)
1. In your repo, click **Settings** (the tab with the gear icon at the top of the repo, *not* your account settings).
2. In the left sidebar, click **Secrets and variables**, then **Actions**.
3. Click the green **New repository secret** button. Enter the **Name** exactly as shown below, paste the **Secret**, and click **Add secret**. Repeat for each one:

| Name | What to paste | Example |
|---|---|---|
| `SMTP_EMAIL` | The Gmail address that sends the texts | `myscanner@gmail.com` |
| `SMTP_APP_PASSWORD` | The 16-letter app password from step 4 | `abcd efgh ijkl mnop` |
| `ALERT_PHONE` | Your 10-digit mobile number, digits only | `5551234567` |
| `ALERT_CARRIER_GATEWAY` | Your carrier's email-to-text domain (table below) | `vtext.com` |
| `SEC_CONTACT_EMAIL` | **Needed for insider buying.** Any email you check. The SEC requires one with automated requests. | `me@gmail.com` |

| Carrier | Gateway |
|---|---|
| Verizon | `vtext.com` |
| T-Mobile / Mint / Metro | `tmomail.net` |
| Google Fi | `msg.fi.google.com` |
| US Cellular | `email.uscc.net` |
| Cricket | `mms.cricketwireless.net` |
| AT&T | ❌ discontinued in 2025, so use ntfy (5b) |

If any of these secrets are missing, the scanner still runs and updates the dashboard. It just logs "SMS skipped" instead of texting you.

#### 5b. (Optional, recommended) Free push notifications with ntfy
1. Install the **ntfy** app (iPhone App Store or Google Play). It's free and doesn't require an account.
2. In the app, tap **+** and subscribe to a topic name that's hard to guess, like `daniel-scanner-7f3k9q`. Anyone who knows the name can read the messages.
3. Add one more repository secret: name **`NTFY_TOPIC`**, value: that same topic name.

#### 5c. (Optional) Reddit keys: add Reddit to the Trending tab and the social signal

> As of 2025, Reddit requires approval for new API apps (its "Responsible Builder Policy"). Trending works without Reddit, using StockTwits and Bluesky, so you can skip this.
1. While logged in to Reddit, go to **https://www.reddit.com/prefs/apps**, scroll down, and click **create another app…**
2. Name: `stock-scanner`. Choose **script**. Redirect URI: `http://localhost:8080`. Click **create app**.
3. The short code under "personal use script" is your client ID. The value next to **secret** is your client secret.
4. Add them as repository secrets named **`REDDIT_CLIENT_ID`** and **`REDDIT_CLIENT_SECRET`**.

Without these, the Trending tab stays off and the social signal uses Wikipedia page views (and Google Trends when it isn't blocked).

**How Trending works:** twice a day, with no signup needed, it reads **StockTwits** (a stock-only social network: its top-30 trending list, plus messages per day for every tracked ticker) and **Bluesky** (public post search for each tracked ticker and brand). Reddit is added if you have keys. It picks out companies from `$TICKER` cashtags and the brand list in **`brands.json`** (e.g. "hoka" → DECK; edit it to add brands you notice), then compares each name's chatter with its own normal level. That needs about 5 days of history first. Names that are rising and not on your watchlist get the full five-signal check automatically. Private brands (Stanley, Owala…) are shown, but there's nothing to buy. TikTok and Instagram aren't included: their APIs aren't open to personal projects, and scraping breaks their terms.

### 6. Turn on the dashboard (GitHub Pages)
1. In your repo, click **Settings**, then **Pages** in the left sidebar.
2. Under **Build and deployment**, **Source**: choose **Deploy from a branch**.
3. **Branch:** choose **main**, change the folder dropdown from `/ (root)` to **`/docs`**, and click **Save**.
4. Wait 1–2 minutes and refresh the page. A box at the top shows your site's address, something like **`https://YOUR-USERNAME.github.io/stock-trend-scanner/`**. Bookmark it.

### 7. Run the first scan
1. Click the **Actions** tab in your repo. If you see a button that says *I understand my workflows, go ahead and enable them*, click it.
2. In the left list, click **Scan watchlist**.
3. On the right, click **Run workflow**, then the green **Run workflow** button.
4. After about 3–5 minutes the run gets a green ✓. (Click it to see the log of every signal for every ticker.) Open your dashboard address and you should see scores.

After this it runs on its own every weekday at about 8:30am and 5:30pm New York time.

### 8. Install the dashboard on your phone
- **iPhone:** open the dashboard address in **Safari**, tap the **Share** button (the square with an arrow), then tap **Add to Home Screen**.
- **Android:** open it in **Chrome**, tap the **⋮** menu, then tap **Install app** (or **Add to Home screen**).

---

## Everyday use

- **What gets scanned:** every **S&P 500 stock** (about 500) plus your `watchlist.json` (marked ⭐) plus rising Trending names, twice each weekday. The Signals tab opens on **Highlights**: alerts, watch-tier stocks and your list. Use the filters or the search box for anything else.
- **Two tiers:** 🔔 **Alert** (score ≥ `alert_threshold`, 5.0) texts you. 👀 **Watch** (score ≥ `watch_threshold`, 3.5) shows in the app and in your evening summary text, with no separate text.

- **Daily summary text:** after the market closes each weekday (the 5:30pm New York scan), you get one text. It lists any **S&P 500 stock that fell 10% or more that day**, then alerts, today's top scores, and names rising on Trending. Change the 10% (or turn the summary off) in `config.json` → `daily_summary`. The same drop list appears on the dashboard. Note that a big drop is a reason to look, not to buy: drops caused by bad news often keep falling.

- **Edit the watchlist:** in your repo, click `watchlist.json`, click the ✏️ pencil icon, edit, then click **Commit changes**. Each entry has a Google-search `keyword` and a `ticker`, for example `{"keyword": "Celsius energy drink", "ticker": "CELH"}`. Don't remove the commas between entries.
- **Change weights, the threshold, or the hold period:** edit `config.json` the same way. `alert_threshold` (0–10), `hold_days` (default 10), and `alert_cooldown_days` (how long to wait before texting about the same stock again) are near the top.
- **Paper trading:** on the dashboard, tap a stock, then **Paper-trade →**, which fills in the ticker and last price. Enter a dollar amount and tap **Add trade**. To close it later, go to **Paper trades → Close trade**. The dashboard shows a planned exit date based on `hold_days`. Your cash, P/L and win rate update automatically.
- **Back up your paper trades:** they're saved **only on that phone's browser**. Use **Settings & backup → Export backup** now and then.
- **Track record:** the Signals tab shows how past alerts actually did over `hold_days` compared with SPY. Every alert is bought at the next day's close (so there's no peeking at prices the scan already saw). The numbers mean nothing until there are dozens of completed tests.

### Why 10-day holds?
The two best-supported signals (earnings drift, insider buying) play out over weeks. Social spikes reverse within days. Ten trading days is a compromise between them. Change `hold_days` in `config.json` to experiment.

### Why "forward testing" instead of a 10-year backtest?
Most of these signals can't be rebuilt for past dates for free (old short-interest snapshots, old Reddit and Trends baselines, old insider screens). A backtest that uses today's data for past dates quietly "sees the future" and looks better than reality. So the scanner logs every score it produces, and `scanner/backtest.py` grades each alert after `hold_days`. It's slower but honest.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| No `.github` folder in the repo after upload | Click **Add file → Create new file**. In the name box, type `.github/workflows/scan.yml` (the slashes create folders). Open `scan.yml` from the project folder in TextEdit, copy all of it, paste it in, and click **Commit changes**. Repeat for `tests.yml`. |
| Workflow fails at "Commit results" with a permission error | **Settings → Actions → General →** scroll to *Workflow permissions* → **Read and write permissions** → **Save**. |
| Dashboard says "No scan has run yet" | Do step 7. |
| Dashboard shows old data on the phone | Tap the ↻ button at the top. The app keeps the last copy so it still works offline. |
| No texts arriving | Open the latest run in the **Actions** tab, click **Scan and alert**, and look for lines starting with `[alerts]`. Most of the time a secret name is misspelled or the carrier is quietly dropping the messages. Set up ntfy (5b). |
| Scans stopped running | GitHub pauses schedules in repos with no activity for 60 days. The scanner's own commits usually count as activity. If it does pause, the Actions tab shows an **Enable workflow** button. |

---

## For the curious: project layout

```
config.json               weights, alert threshold, hold period, every signal's settings
watchlist.json            keyword -> ticker list
scanner/
  signals/                one module per signal (+ stubs.py for the not-implemented ones)
  scoring.py              composite score + explanation (pure math)
  alerts.py               email-to-SMS + ntfy
  run_scan.py             the entry point the GitHub Action runs
  backtest.py             forward-test of logged alerts
docs/                     the dashboard (GitHub Pages serves this folder)
  data/                   scan results the Action commits (results / history / backtest)
  papertrade.js           paper-trading math (shared with the tests)
tests/                    offline unit tests - no internet needed
.github/workflows/        scan.yml (scheduled scanner), tests.yml (runs tests on every change)
```

Running it locally (optional, needs Python 3.9+):

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -t .      # Python tests
node --test tests/papertrade.test.js            # JS tests (needs Node 18+)
python -m scanner.run_scan --no-alerts          # a real scan, no texts
```
