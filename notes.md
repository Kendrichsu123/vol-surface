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
data/ — dated snapshot archive (gitignored), one CSV per day.


The if __name__ == "__main__": guard is what lets data.py be BOTH an
importable library AND a runnable script — plotting only fires when run
directly, not when collect.py imports it.


Key decisions


Mid-price (bid+ask)/2, not last price — last can be hours stale.
OTM options only (puts below spot, calls above) — more liquid, the
CBOE/VIX convention. Deep ITM options are wide and illiquid.
Filters: OTM only, bid > 0, spread/mid < 0.5, openInterest > 0.
Assumptions: r = 0.045 (T-bill), q = 0.012 (SPY div yield).
Log-moneyness ln(K/S) instead of raw strike for the surface — normalizes
expiries so their smiles are comparable (a 700 strike is deep OTM for a
1-week option but near-ATM for a 1-year option).
Expiry sampling spy.options[:40:3] — every 3rd expiry out to the 40th,
to span days-to-years instead of clustering in the near-dated dailies.
Snapshot time: ~3pm ET daily. Consistency matters more than the exact
hour — IV drifts intraday, so a fixed time controls for that drift. 3pm is
during market hours (tight spreads, live quotes) vs. the messier close bell.



Things I learned / bugs I hit


^ is XOR in Python, not power — use **. (BS d1 formula.)
VS Code runs the file ON DISK — must save (Cmd+S) before running.
brentq needs f(a), f(b) opposite signs; the "different signs" error means a
bad quote with no valid IV (price violates arbitrage bounds) -> filter it out.
So that error is really brentq doing data-quality checking for me.
git: add -> commit -> push. Commit alone doesn't publish. git add stages,
git commit checkpoints locally, git push publishes to GitHub.
Silent copy-paste bug: had puts["bid"] + calls["ask"] for the put mid —
ran fine, just wrong. Caught it via the yfinance IV benchmark. Lesson: silent
bugs are why benchmarking against an independent source matters.
T <= 0 guard: a same-day expiry gives T=0 -> divide-by-zero in d1. A
function that computes T should refuse a non-positive T, not trust the caller.
[:12] gives the 12 NEAREST expiries, not 12 spread out — SPY has daily
expiries so they all landed within 3 weeks. Had to step with [:40:3].
yfinance is flaky — "possibly delisted; no price data" usually means
rate-limited, not delisted. Wait and retry. Guard empty returns explicitly.
The __main__ guard is the line between "importable library" and "runnable
script." Un-guarded code runs on import — which would pop plots when
collect.py imports data.py.



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

bashsource venv/bin/activate      # if (venv) not already showing
python collect.py

Expect: Saved ~1700 rows to data/surface_YYYY-MM-DD.csv and NO plot windows.
If it errors with "no price data" -> yfinance rate-limited, wait 60s and rerun.

Rules:


Same time each day (consistency controls for intraday drift).
Skip weekends / market holidays (market closed, no data).
Running twice in one day just overwrites that day's file — harmless.
A missed day is OK; small gaps are fine.


CRITICAL DATES (do not miss):


July 27 — last snapshot BEFORE FOMC (pre-event baseline).
July 28-29 — FOMC meeting.
July 30 — first snapshot AFTER announcement (the crush).
Keep collecting a few days after to see the term structure normalize.


Collection started: 2026-07-08.


TODO


 Run collect.py daily through early August.
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
Hardest bug: the silent put-mid copy-paste error, caught by benchmarking.