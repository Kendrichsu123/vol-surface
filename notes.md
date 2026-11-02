Vol Surface — Project Notes

What this project does

Pulls live SPY option chains, backs out implied volatility from market prices
using a Black-Scholes engine I wrote, and builds/visualizes the full implied
volatility surface (IV as a function of strike and expiry). Then collects daily
snapshots to study how the surface moves around a scheduled macro event (FOMC).


Research question / hypothesis (Phase 4)

Event: FOMC meeting, July 29-30, 2026.

Hypothesis: The IV term structure will show an elevated "hump" at the expiry
that brackets the FOMC date in the days before the meeting (options priced
across the event embed the uncertainty as extra vol), and that hump will
collapse the day after the announcement once the uncertainty resolves —
"IV crush." Same mechanism traders see around earnings.

What I'm measuring (daily):


ATM term structure — at-the-money IV vs. expiry. The post-July-29 expiry
should sit above the smooth trend pre-FOMC, then drop into line post-FOMC.
Skew steepness per expiry (25-delta put IV minus 25-delta call IV) — to see
if the shape shifts around the event, not just the level.


Why it's good material: real market-microstructure phenomenon, quantified,
uses the whole pipeline, and connects to trading (desks sell elevated pre-event
vol and buy it back cheap after).

Honest limitation: single event = n=1, an anecdote not a statistical result.
Framed as a case study of a known effect. Would need multiple FOMC dates for
significance.


Architecture


main.py — the engine: Black-Scholes pricer (bs_price) and implied-vol
solver (implied_vol). Imported by everything else.
data.py — the library: smile_for_expiry, build_surface,
save_daily_surface. Plus a __main__ block that draws the 3D surface +
heatmap when run directly (python data.py).
collect.py — the daily job: imports from data.py, saves a dated snapshot.
data/ — dated snapshot archive, one CSV per day. Committed: option chains
cannot be re-queried historically, so every snapshot is a one-shot record.


data.py is both an importable library and a runnable script: the plotting
lives behind a __main__ guard, so it fires when you run the file directly and
stays quiet when collect.py imports it.


Key decisions


Mid-price (bid+ask)/2, not last price — last can be hours stale.
OTM options only (puts below spot, calls above) — more liquid, the
CBOE/VIX convention. Deep ITM options are wide and illiquid.
Filters: OTM only, bid > 0, spread/mid < 0.5, openInterest > 0.
Assumptions: r = 0.045 (T-bill), q = 0.012 (SPY div yield).
Log-moneyness ln(K/S) instead of raw strike for the surface — normalizes
expiries so their smiles are comparable (a 700 strike is deep OTM for a
1-week option but near-ATM for a 1-year option).
Expiry sampling — originally spy.options[:40:3], every 3rd expiry out to
the 40th. SUPERSEDED on 2026-07-27: selecting by list position rotates the
ladder as contracts expire. Now selected by target date offset; see the
collector rewrite below.
Snapshot time: ~3pm ET daily. Consistency matters more than the exact
hour — IV drifts intraday, so a fixed time controls for that drift. 3pm is
during market hours (tight spreads, live quotes) vs. the messier close bell.



Things I learned / bugs I hit

brentq needs f(a), f(b) opposite signs; the "different signs" error means a
bad quote with no valid IV (price violates arbitrage bounds) -> filter it out.
So that error is really brentq doing data-quality checking for me.
Silent copy-paste bug: had puts["bid"] + calls["ask"] for the put mid —
ran fine, just wrong. Caught it via the yfinance IV benchmark. Lesson: silent
bugs are why benchmarking against an independent source matters.
T <= 0 guard: a same-day expiry gives T=0 -> divide-by-zero in d1. A
function that computes T should refuse a non-positive T, not trust the caller.
[:12] gives the 12 NEAREST expiries, not 12 spread out — SPY has daily
expiries so they all landed within 3 weeks. Had to step with [:40:3].
yfinance is flaky — "possibly delisted; no price data" usually means
rate-limited, not delisted. Wait and retry. Guard empty returns explicitly.



Observations about the data (the finance showing up)


Equity skew/smirk: deep OTM puts imply ~52% vol vs. ~13% ATM (short-dated).
Downside puts are "expensive" in vol terms — crash-insurance premium, fat left
tail, leverage effect. Post-1987 this skew became permanent.
Skew flattens with maturity: short-dated smiles are steep, long-dated
smiles are gentle. Visible in both the 3D surface and heatmap.
Vol trough sits slightly above spot, near the forward price, not exactly
at spot.
More liquid OTM puts than calls (funds buy downside protection) — put wing
keeps more strikes than call wing after filtering.
The triangular data region: near-dated options only have strikes close to
spot (stock can't travel far in a week); far-dated options have strikes ranging
enormously far. Available strike range widens ~ with sqrt(time). The white
space in the heatmap is "no options exist there," not missing data.
My IV matches yfinance's within ~1 vol point. Residual gap likely from
spot timing / q assumption / mid-vs-last price. (This is the validation that
the whole pipeline is correct.)
Far-dated deep-OTM puts are the noisiest / least reliable part of the surface
(illiquid).



Limitations (for README)


SPY options are American-style; Black-Scholes prices European. Fine for
short-dated OTM options (early-exercise premium tiny there), but an
approximation. ^SPX options are European if I want purity later.
T = calendar days / 365, not trading days / not counting to market close.
Flat r and q, not a term structure or forward-implied.
One snapshot per day — can't see intraday surface dynamics, only day-over-day.
Single FOMC event — case study, not a statistical result.



DAILY COLLECTION INSTRUCTIONS

Run every trading day (~3pm ET), from the vol-surface folder:

source venv/bin/activate      # if (venv) not already showing
python collect.py

Expect: Saved ~1700 rows to data/surface_YYYY-MM-DD.csv and NO plot windows.
If it errors with "no price data" -> yfinance rate-limited, wait 60s and rerun.

To take a second snapshot in the same day without overwriting the first:

python collect.py --label pre
python collect.py --label post

-> data/surface_YYYY-MM-DD_pre.csv, data/surface_YYYY-MM-DD_post.csv

Rules:


Same time each day (consistency controls for intraday drift).
Skip weekends / market holidays (market closed, no data).
Running twice in one day overwrites that day's file unless you pass --label.
A missed day is OK; small gaps are fine.


CRITICAL DATES (do not miss):


July 27 — last snapshot BEFORE FOMC (pre-event baseline). DONE.
July 28 — FOMC day 1. Normal 3pm snapshot.
July 29 — FOMC day 2. ANNOUNCEMENT IS 2:00pm ET, NOT AFTER THE CLOSE.
  Run TWICE: `--label pre` at ~1:00pm ET (last clean pre-announcement read)
  and `--label post` at the usual 3:00pm ET. Same day, same expiry ladder,
  same spot regime — that pair IS the crush measurement, and it's much
  cleaner than a day-over-day comparison.
July 30 — normal snapshot; day-after confirmation.
Keep collecting a few days after to see the term structure normalize.


NOTE: an earlier version of these notes said "July 30 = first snapshot after
the announcement." That was wrong — the FOMC statement lands at 2pm ET on the
second day of the meeting, so a 3pm snapshot on July 29 is already post-crush.
Hence the pre/post pair on the 29th.


Collection started: 2026-07-09.


COLLECTOR REWRITE (2026-07-27) — what changed and why


1. Expiry selection is now by TARGET DATE OFFSET, not list index.

The old spy.options[:40:3] selected by POSITION. As expiries roll off the
front the list shifts, so the every-3rd stride lands on different dates each
day. Measured across the first 13 snapshots: 41 distinct expiries sampled, and
no single expiry present in more than 7 of the 13. The 2026-07-31 expiry — a
natural one to track through the event — appears in only 6, and is missing
from four of the five sessions in the final run-up week (present 07-23 only).

Now: nearest listed expiry to each of [1, 3, 7, 14, 30, 60, 90, 180, 365, 730]
days, unioned with an ALWAYS_INCLUDE list of the FOMC-bracketing expiries.
Verified stable: 07-30, 07-31, 08-07 and 08-21 are now present in every run
from 07-27 through the event window.

Consequence for analysis: snapshots BEFORE 07-27 have the rotating ladder.
Per-day term structure still works fine on them (that's what showed the
inversion). Fixed-expiry time series only works cleanly from 07-27 forward.


2. CSV schema is wider.

Old:  log_moneyness, T, iv, spot, snapshot_date
New:  expiry, T, strike, log_moneyness, option_type, iv, delta,
      bid, ask, mid, openInterest, spot, snapshot_date, snapshot_ts

delta is stored so the planned 25-delta skew metric is a direct computation
instead of a re-derivation. bid/ask/openInterest are kept so a suspicious
point can be audited after the fact instead of being unrecoverable.
snapshot_ts records the actual run time — the 7/15 3:45pm run should have
been in the data, not only in prose.

Reading old files: they have no `expiry` column, but it's recoverable exactly
as snapshot_date + round(T*365) days (verified to 1e-13 across all 13 files).


3. T is now a fraction of a year to 4:00pm ET, not whole calendar days.

Calendar-day resolution gives T=0 for a same-day expiry, which divides by zero
in d1 and drops the contract. On FOMC day the 0DTE contract is the single most
informative one on the board, so it needs time-of-day resolution. For anything
a week or more out the difference is under ~1.3% in T (well under a vol point)
— this matters for 0-2DTE only.

Consequence: T in files from 07-27 onward is fractional; in earlier files it's
whole days. Compare via `expiry`, not via raw T.


4. run_collect.sh fails loudly.

Previously: no error checking at all. If collect.py died (yfinance rate limits,
which happens), git staged nothing, the commit no-op'd, and the script still
exited 0 — a silent miss. Now it checks the exit code, verifies the expected
file exists before committing, retries the push with backoff, and exits
non-zero on failure. Takes an optional label argument: ./run_collect.sh pre


5. main.py tests are asserts, not prints.

A printed test can't fail. Added delta coverage (bounds + put/call delta
parity). Run with: python main.py


TODO


 Run collect.py daily through early August.
 July 29: run BOTH --label pre (~1pm ET) and --label post (~3pm ET).
 Clean up filters if needed (consider a min-price floor > $0.10 on the wings).
 Phase 4 analysis script (early August, once data is in):
load all data/*.csv, extract ATM IV per expiry per day, plot the
term-structure hump rising into July 29 and collapsing after; same for
skew metric.
 README with hypothesis, method, key charts (smile, surface, heatmap,
the FOMC result), and limitations.
 Stretch: fit SVI to each smile; compare SPY vs. a single name (NVDA).



Interview talking points (the "walk me through this project" answer)


Built a BS pricer + IV inverter from scratch; IV is a root-find (can't invert
BS algebraically) — used Brent's method (hybrid bisection/secant).
Pipeline handles real market microstructure: mid vs. last, liquidity filters,
arbitrage-violating quotes that break the solver.
Validated my IV against an independent source to ~1 vol point.
Read the surface: equity skew (crash premium), skew flattening with maturity,
term structure.
Studying FOMC vol crush — a real thing desks position around.



Error Fix on 7/15 at 3:45pm. Lost wifi connection so lost virtual environment; surface_2026-07-15.csv was not created at 3pm and instead created at 3:45pm

Pre-event eyeball: front-expiry IV up ~40-50% vs mid-July, but confounded by shorter T and a 2% spot decline. Need matched-maturity comparison in analysis."