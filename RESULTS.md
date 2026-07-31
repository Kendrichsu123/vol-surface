# Results — FOMC event premium, July 2026

A chronological account: what was expected, what was collected, what went
wrong, what was done about it, and what the data actually showed.

Companion to `EXPLAINER.md`, which teaches the concepts and walks the story in
plain language. This document is the record: every number, and what went wrong
when.

---

## 0. The question

The FOMC announcement of **Wednesday July 29, 2026 at 2:00pm ET** is a
scheduled event with a known date. Two predictions:

1. Before the announcement, option expiries spanning July 29 should imply more
   volatility than their maturity alone justifies — an **event premium**.
2. At 2:00pm that premium should collapse, because the uncertainty it
   compensated for no longer exists.

Note the term: **event premium**, not "volatility risk premium." VRP is the gap
between implied and *subsequently realized* volatility. This project never
observes realized volatility; everything here is read off option prices at a
point in time.

---

## 1. Build phase

Three components, written before collection began.

**`main.py` — the pricer.** Black-Scholes for European options, plus `bs_delta`.
Validated by three assertions: a textbook ATM value (7.9656), put-call parity,
and a round trip (price at a known sigma, invert, recover it).

**`main.py: implied_vol` — the inverter.** Black-Scholes has no algebraic
inverse in sigma, so implied volatility is a root-find. Brent's method on
`[1e-6, 5.0]`. Its failure mode is useful: if the function doesn't change sign
across that bracket, no volatility in 0.0001%–500% reproduces the quoted price,
which means the quote violates a no-arbitrage bound. **The solver doubles as a
data-quality filter.**

**`data.py` — the pipeline.** Pull the chain, filter, invert, normalise:

| Decision | Reason |
|---|---|
| mid price `(bid+ask)/2` | last trade can be hours stale |
| OTM only | ITM options are wide, illiquid, mostly intrinsic value |
| `bid > 0`, `spread/mid < 0.5`, `openInterest > 0` | drop meaningless quotes |
| log-moneyness `ln(K/S)` | makes expiries comparable |

Two bugs were found and fixed during the build, both recorded in `notes.md`:

- **`puts["bid"] + calls["ask"]`** for the put mid — a copy-paste error that ran
  without complaint and produced wrong numbers. Caught by benchmarking against
  yfinance's own IV. This is the reason the pipeline is validated against an
  independent source at all.
- **`spy.options[:12]`** returned the 12 *nearest* expiries. SPY has daily
  expiries, so all 12 landed inside three weeks. Changed to `[:40:3]`.

That second fix contained the bug that later mattered most.

---

## 2. Collection phase 1 — schema v1 (July 9–27)

A `launchd` agent ran `run_collect.sh` at **15:00 ET** each trading day.

**13 snapshots collected**, ~1,700 rows each, 9–11 expiries per snapshot:

```
07-09  1898 rows  11 exp  spot 751.71     07-21  1735  10  748.41
07-10  1855       10      754.46          07-22  1809  10  748.46
07-13  1889       11      749.47          07-23  1640   9  737.05
07-14  1810       10      752.12          07-24  1707  11  738.53
07-15  1688       10      753.74 (15:45)  07-27  1693  10  739.03
07-16  1834       11      750.26
07-17  1793       10      744.35
07-20  1769       10      742.77
```

One irregularity: **07-15 ran at 15:45, not 15:00** — a wifi outage killed the
scheduled run. Recorded in `notes.md` at the time; the v1 schema had no
timestamp column to record it in the data.

Schema v1: `log_moneyness, T, iv, spot, snapshot_date`. `T` in whole calendar
days ÷ 365.

---

## 3. The July 27 review — three problems

### 3.1 The expiry ladder was rotating (critical)

`spy.options[:40:3]` selects by **list position**, not by date. As expiries
roll off the front the list shifts, so the every-third stride lands on a
different set of dates each day.

Measured across the 13 snapshots: **41 distinct expiries, and no single expiry
present in more than 6 of them.** The `2026-07-31` expiry — a natural one to
track through the event — was absent from the entire final run-up week
(07-21 through 07-27).

This would have made "track one contract's IV as it rises into the event and
collapses after" impossible. Fixed by selecting the nearest listed expiry to a
fixed set of horizons `[1, 3, 7, 14, 30, 60, 90, 180, 365, 730]` days, plus a
hard-coded list of FOMC-bracketing dates. Verified stable: `07-30`, `07-31`,
`08-07`, `08-21` appear in every run from 07-27 onward.

### 3.2 The schema was lossy

`strike`, `option_type`, `delta`, `bid`, `ask`, `mid`, `openInterest`, and
`snapshot_ts` were all added. `delta` matters because the planned 25-delta skew
metric quotes skew at equal *delta*, not equal strike. `bid`/`ask` matter
because without them you cannot audit a suspicious point after the fact.

**This decision is what made the later forward correction possible.** Option
chains cannot be re-queried historically — yfinance serves only the live book —
so every snapshot is a one-shot observation and anything not saved is gone.

### 3.3 The announcement time was wrong in the notes

`notes.md` said "July 30 — first snapshot AFTER announcement." But the FOMC
statement lands at **2:00pm ET on the second day of the meeting**, so a 3:00pm
snapshot on July 29 is *already* post-crush. A day-over-day comparison would
have confounded the crush with a full session of unrelated movement.

Changed to a **same-day pre/post pair**: 1:00pm and 3:00pm on July 29. Two hours
apart means `T` is effectively unchanged, the expiry ladder is identical, spot
has barely moved, and there is no overnight gap.

### 3.4 Also fixed

- `T` changed from whole calendar days to a year fraction to 4:00pm ET. Calendar
  resolution gives `T = 0` for a same-day expiry, dividing by zero in `d1` — and
  on FOMC day the 0DTE contract is the most informative one on the board.
- `run_collect.sh` given exit-code checking, output verification, and push
  retries. Previously a failed collection exited 0 silently.
- Pricer tests converted from `print` to `assert`. A printed test cannot fail.

---

## 4. Collection phase 2 — schema v2 (July 28 onward)

```
07-28 15:00  2046 rows  14 expiries  spot 741.49
07-29 13:00  2082 rows  14 expiries  spot 734.93   <- pre-announcement
07-29 15:00  2024 rows  14 expiries  spot 742.02   <- post-announcement
```

```
07-30 15:00  ~2000 rows  14 expiries  spot 740.79   <- day after
07-31 15:00  ~2000 rows  12 expiries  spot 746.44   <- term structure normalised
```

**18 snapshots total** (13 v1 + 5 v2), July 9 through July 31.

### The forward bias — discovered July 28

A manual 10:04am run exposed something the 3pm snapshots had been hiding. On
the 0DTE expiry, the **737 put implied 33.3%** while the **738 call implied
20.4%** — one strike apart.

That is not noise. Put-call parity off those quotes gives `C(737) = 2.77`
against an observed `C(738) = 1.295`, so a one-point vertical spread priced at
**$1.48 when its ceiling is $1.00** — an arbitrage violation, meaning the
quotes are internally inconsistent.

**Cause:** spot and the option chain come from different feeds with different
timestamps. Solving for the forward that reconciles the wings gave ~736.35
against the 737.40 used — the spot ran roughly **1 point stale**.

**It was not new.** Measuring the same put/call gap across every prior snapshot:

```
07-09 +0.2   07-14 -1.6   07-17 +3.7   07-22 +0.5   07-27 +5.4
07-10 +0.6   07-15 +0.3   07-20 +0.7   07-23 +0.6
07-13 +0.9   07-16 -2.1   07-21 -0.6   07-24 +2.0
```

**Signature:** the gap decays with maturity, exactly as a forward error must —
the same dollar error is a smaller fraction of a wider distribution. A genuine
market feature would not behave that way. On the 07-27 snapshot:

| expiry | days | put ATM | call ATM | gap |
|---|---|---|---|---|
| 2026-07-30 | 3 | 22.4% | 17.0% | +5.4 |
| 2026-08-04 | 8 | 18.0% | 14.8% | +3.2 |
| 2026-08-28 | 32 | 16.4% | 15.1% | +1.3 |
| 2027-06-30 | 338 | 19.2% | 18.9% | +0.2 |

**This corrected an earlier claim.** An initial reading of 07-27 interpolated
across both wings and reported a **4.3 vol-point** hump at the event expiry.
That was dragged up by the put wing. Wing-averaging — which cancels an
antisymmetric error to first order — gives **~3 points** (19.7% at 3 days
against 16.4% and 16.7% behind it).

Decision: **do not change the collector before the event.** The stored columns
were sufficient to correct this offline, and changing collection code the day
before an unrepeatable measurement was not worth the risk.

---

## 5. The event — July 29

### The pre-registered prediction, written at 1:00pm

Computed from the 1pm snapshot, **before any post-event data existed**:

```
spot 734.93
implied move to the 4pm close   +/- 1.07%  (+/- 7.88 pts)
1-sigma close range             727.05 - 742.81
the market prices these 3 hours at 3.1x an ordinary 3-hour window
excess attributable to the Fed  +/- 0.88%

[SUPERSEDED: the 3.1x rests on the 0DTE expiry, which later failed forward
 calibration and carries the largest wing gap in the dataset. Treat it as an
 upper bound. See section 7. The forecast itself still verified out-of-sample.]

predicted 3pm ATM IV once event variance is released:
  2026-07-30   28.9% -> 25.1%
  2026-07-31   25.3% -> 22.9%
```

### What happened

**Realized move 1pm → 3pm: +0.964%** (734.93 → 742.02). But the 3pm snapshot
landed near a transient peak: SPY fell to roughly 730 by 3:55pm, so the move
over the window the forecast actually covered — 1pm to the 4pm close — was
**−0.671%**. Still inside the predicted band, but the market delivered *less*
net movement than priced, not more. Note also the path: SPY covered 730–743, a
1.8% intraday range, to finish 0.67% lower. Options price the terminal
distribution, not the path. Inside the predicted
±1.07% band, with an hour still to the close.

```
expiry        days   ATM pre   ATM post   change
2026-07-29     0.1     58.0%      54.9%     -3.2
2026-07-30     1.1     28.9%      22.1%     -6.8
2026-07-31     2.1     25.3%      19.7%     -5.6
2026-08-07     9.1     18.2%      15.5%     -2.7
2026-08-21    23.1     16.8%      14.4%     -2.4
2026-10-30    93.1     16.6%      15.6%     -1.0
2027-06-30   336.1     18.7%      18.2%     -0.5
2028-06-16   688.1     21.0%      20.7%     -0.3
```

### Where the prediction missed, and why that is the interesting part

The crush was **larger** than forecast — 07-30 fell to 22.1%, not the predicted
25.1%. The forecast only removed *event* variance. Volatility **also fell
market-wide**, which the long end shows independently.

Decomposing in variance space (variance is additive in time, so this is the
natural parameterisation):

```
dV(T) = a + b*T
  all expiries    a = 3.02e-4 -> 1.74%   b = +0.00119   R2 = 0.912
  <=60d only      a = 1.10e-4 -> 1.05%   b = +0.00504   R2 = 0.961
```

### Caveat — the market-wide component may be a measurement effect

SPY rose 0.96% between the two snapshots. Because of skew, "at-the-money" at
742 is a different point on the smile than at-the-money at 735, so if the smile
stays fixed in strike space, ATM volatility falls mechanically as spot rises —
without any real volatility change.

The predicted size of that effect closely matches the "market-wide" component
at most maturities (e.g. 2027-06-30: predicted -0.42 vol pts, observed -0.47;
2026-10-30: predicted -0.92, observed -0.89). Removing it leaves the variance
released roughly flat across maturity, which is the signature of a pure one-off
event with no second component.

**What this changes:** the event estimate holds (corrected central value 1.09%,
range 0.84-1.30%, against the 0.95% reported above). The claim of a *separate
market-wide decline* is the part in doubt, and the 1.9 vol point figure should
not be quoted without this caveat.

**What is unresolved:** the correction assumes the smile is fixed in strike
space ("sticky-strike"). If it instead travels with spot ("sticky-moneyness"),
no correction is needed and the original two-component reading stands. Real
markets sit between. A single spot move cannot distinguish them — that needs
several events with different spot moves.

Two separable effects: a **one-off release** (`a`) and an **ongoing
variance-rate decline** (`b`). A naive analysis would have merged them and
reported a larger event.

An earlier attempt to fit `dIV = a/T + b` in *implied-vol* space failed at
**R² = 0.02** — wrong space. Variance is the additive quantity.

---

## 6. Post-processing

**`surface_io.py`** normalises both schema eras into one frame. Everything v1
omitted is recoverable exactly except `bid`/`ask`/`openInterest`:

```
expiry      = snapshot_date + round(T*365)     exact, verified to 1e-13
strike      = spot * exp(log_moneyness)        exact
option_type = sign of log_moneyness            exact (OTM-only filter)
mid         = bs_price(S, K, T_v1, r, iv, q)   exact
```

v1 rows are re-inverted onto the corrected clock. The correction is **−0.163
vol points at 3 days, under −0.014 beyond a month**, and negative everywhere —
v1's whole-day `T` understated remaining life and so overstated IV. Small, but
the convention changed on 07-28, one day before the event, and an artificial
step there would sit exactly where a real one is being claimed.

A bug was found and fixed while testing this: parsing `snapshot_ts` with
`pd.to_datetime` produced a pandas `Timestamp` whose arithmetic against a
`ZoneInfo`-aware expiry **silently dropped exactly 3600 seconds** for expiries
past the EST/EDT boundary — 392 of 1693 rows, visible only on the December and
January expiries. Fixed and pinned with a regression test.

**`analysis.py`** does the real correction: for each expiry, solve for the
forward that makes the wings agree, then re-invert every quote against it.
**135/175 expiries (77%)** solve; the rest fall back to wing-averaging.

Measured against the *theoretical* forward `S·e^((r-q)T)` rather than raw spot,
so carry is not mistaken for staleness:

```
  <1w    median -0.184%
  1w-2m  median -0.024%
  >2m    median -0.290%
```

Caveat: the `>2m` figure may be partly the flat `q = 0.012` assumption. A
dividend-yield error moves long-dated forwards the same direction and this data
cannot separate the two.

---

## 7. What the answer is

### The headline number

**The FOMC announcement was worth about ±0.95% of SPY movement.**

That figure comes from fitting `dV(T) = a + b*T` using **only expiries where
forward calibration succeeded in both the 1pm and 3pm snapshots**, restricted
to 30 days and under:

```
calibrated, <=30d    n=5    a = 9.04e-5  ->  0.95%    R2 = 0.996
calibrated, <=60d    n=6    a = 1.27e-4  ->  1.13%    R2 = 0.940
calibrated, all      n=10   a = 2.95e-4  ->  1.72%    R2 = 0.950
```

Ten expiries calibrated in both snapshots. The ≤30-day fit uses five of them,
achieves R² = 0.996, and depends on **none** of the contaminated short-dated
readings. **Take ±0.95% as the point estimate.**

**Uncertainty is wider than that fit suggests.** Correcting for the skew
traversal (the 0.96% spot move sliding the ATM point down the smile) lowers the
≤30-day intercept to **0.62%**, while the flat mean of the corrected releases
gives **1.09%**. Independently, the July 28 snapshot implied a Wednesday
premium of only **0.48%** (see §7, "What is weak"). The defensible range is
therefore roughly
**0.5%–1.1%**, and ±0.95% may sit toward the high end of it.

The all-expiry intercept is leverage-driven — including the 688-day expiry
alone moves it from 1.13% to 1.72% — and that expiry did not calibrate in
either snapshot. Do not quote it.

The 1:00pm forecast of ±0.88% was close to the ≤30-day answer of 0.95%, and
the realized move landed inside the predicted ±1.07% band (−0.671% measured to
the 4pm close, the window the forecast covered; +0.964% measured to the 3pm
snapshot, which caught a transient spike).

### Superseded estimates — do not quote these

Three numbers reported earlier in the study rest on the **0DTE expiry**, which
turned out to be the least reliable series in the dataset. That expiry:

- carries the largest put/call wing gap anywhere in the data (**+30** vol
  points at 1pm, **+38.5** at 3pm)
- **fails forward calibration entirely**, in both snapshots
- implies more variance for three hours than the July 28 snapshot priced for
  the whole of Wednesday (1.07% vs 1.015%) — internally inconsistent

| superseded | value | why dropped |
|---|---|---|
| "3.1× an ordinary 3-hour window" | 3.1× | numerator is the uncalibrated 0DTE; upper bound of unknown tightness |
| "0DTE direct read" | 0.90% | same expiry, same problem; agreement with 0.95% is coincidental |
| front cluster (<15 days) | 1.29% | includes the 0DTE and other uncalibrated expiries |

The 3.1× figure should be treated as **an upper bound, not a measurement.**

### What is solid

1. **The event size, ±0.95%**, from calibrated expiries only, R² = 0.996.
2. **The crush is real.** At 1pm the 07-30 and 07-31 expiries calibrated to
   28.9% and 25.3% — *identical* to their wing-averaged values — so the
   subsequent 6.8 and 5.6 point drops are not artefacts.
3. **Localization.** Front expiries fell 5–7 vol points; the 688-day expiry
   fell 0.3 against a predicted event effect of 0.01. No market-wide shift
   produces that shape. This is the single strongest piece of evidence.
4. **The pre-registered forecast verified out-of-sample.** Written at 1:00pm,
   checked at 3:00pm. Note the forecast itself used the 0DTE, so its accuracy
   is partly luck.
5. **Two effects separated** — the one-off release and the broad
   variance-rate decline.

### What is weak — state this plainly

**The null band is inconclusive.** The crush is only 1.3–1.7× the normal daily
standard deviation at 10–60 day tenors:

```
 tenor    n     sd    p95   worst   crush
   10d   13   2.06   3.83   4.04   -2.71   1.3x sd
   20d   13   1.49   2.86   3.03   -2.45   1.6x sd
   30d   13   1.09   1.95   2.28   -1.82   1.7x sd
   60d   13   0.84   1.55   1.79   -1.25   1.5x sd
```

Worse, **it cannot be computed where the effect is largest.** The crush is at
1–2 days (−6.8, −5.6 vol points), but the rotating v1 ladder almost never
reached below 3 days — the shortest expiry was 3–5 days on every pre-07-27
snapshot. There is no null distribution at the front. The 5-day row rests on
**n = 3** and should not be quoted.

That is a direct downstream cost of the expiry-ladder bug: fixed in time to
capture the event, but not in time to build a baseline at the tenors that
matter.

**There is no consistent pre-event premium in the daily data.** For each
snapshot, the variance rate of the window bracketing July 29, measured against
a maturity-comparable baseline (a consecutive expiry pair in the 14–45 day
range):

```
snapshot   event window   trading days   ratio
07-09      07-20 > 07-31        9        0.90x
07-14      07-22 > 07-31        7        0.97x
07-17      07-27 > 07-31        4        1.15x
07-20      07-28 > 07-31        3        1.33x
07-21      07-24 > 07-29        3        0.80x
07-23      07-28 > 07-31        3        1.37x
07-28      07-28 > 07-29        1        1.07x
```

Most sit below 1.0, and the only snapshot with a tight one-trading-day bracket
shows just 1.07×. Two reasons the pre-event days cannot see the premium: the
rotating ladder rarely provided expiries on both sides of July 29, so the event
is diluted across a multi-day window; and once-daily sampling cannot resolve a
premium that builds through a single morning.

A first attempt at this table used the *longest* expiries as the baseline and
produced ratios below 1.0 everywhere. That was wrong — SPY's long-dated ATM
vol (~21%) naturally exceeds short-dated (~15%), so a far window always looks
busier per unit time. The baseline must be maturity-comparable.

**An unresolved inconsistency.** As of July 28 at 3pm, the market priced
Wednesday's excess variance at roughly 0.48%. The realized crush released
0.95–1.13%. Either the premium roughly doubled between Tuesday afternoon and
Wednesday 1pm, or the `a + b*T` decomposition is not fully separating the event
from the concurrent market-wide move. **Once-daily sampling cannot distinguish
these.** This is the strongest argument for intraday snapshots at the next
event.

**n = 1.** One meeting is a case study of a known effect, not a statistical
result. Establishing significance needs many event dates.

**Other limitations.** SPY options are American
and Black-Scholes prices European; flat `r` and `q`; calendar-time `T` rather
than trading time; liquidity filters bias toward liquid strikes.

---

## 7b. Did the crush hold? — the July 30 test

The one question the post-event data could settle. Spot moved only **−0.17%**
from Wednesday 3pm to Thursday 3pm, so there is no skew-traversal ambiguity in
this comparison.

```
expiry         days      Tue      Wed      Thu   Wed->Thu   wing gap Thu
2026-07-31      1.0    19.4%    19.7%    17.6%     -2.13         2.6
2026-08-04      5.0    15.5%    14.7%    13.0%     -1.77         1.7
2026-08-07      8.0    15.8%    15.4%    14.5%     -0.89         1.0
2026-08-14     15.0    15.3%    14.7%    14.5%     -0.23         0.5
2026-08-21     22.0    15.1%    14.4%    14.5%     +0.03         0.4
2026-08-28     29.0    15.2%    14.8%    14.9%     +0.12         0.2
2026-09-30     62.0    15.2%    14.9%    15.1%     +0.23         1.3
2027-06-30    335.0    18.9%    18.6%    18.6%     +0.05         0.3
```

**The crush held.** At 15–30 days — where the clean signal lives — Thursday sat
within 0.25 vol points of Wednesday, well inside the normal daily fluctuation.
The event premium was released and stayed released. It did not refill toward
the Tuesday level.

**The front kept falling.** The 1–8 day expiries dropped a further 0.9–2.1
points. This confirms the reading of Wednesday's data: the front end was
elevated by *turbulence*, not by the event, and it decayed once the market
settled. The two components separate by their behaviour over time — the event
release is permanent, the turbulence premium decays — which is cleaner evidence
than the regression in section 7.

**Data quality returned to normal.** Thursday's put/call wing gaps are 0.2–2.6
vol points against Wednesday's 5–8, confirming those wide gaps were the fast
tape rather than anything systematic in the pipeline.

### July 31 — the term structure fully normalises

One more trading day closes the arc. SPY rose a further 0.76%.

```
expiry         days      Wed      Thu      Fri   Thu->Fri   wing gap Fri
2026-08-07      7.0    15.4%    14.5%    11.9%     -2.56          0.9
2026-08-14     14.0    14.7%    14.5%    12.5%     -1.96          0.5
2026-08-21     21.0    14.4%    14.5%    12.9%     -1.51          0.4
2026-09-30     61.0    14.9%    15.1%    14.3%     -0.81          1.3
2026-10-30     91.0    15.7%    15.9%    15.2%     -0.67          0.8
2027-06-30    334.0    18.6%    18.6%    18.4%     -0.20          0.0
```

**The event premium did not refill.** The 08-21 expiry — the cleanest signal
in §7b — went to 12.9%, further *below* both Wednesday's post-announcement
level and Tuesday's pre-announcement 15.1%. Two consecutive days now confirm
the release was permanent.

**Friday's broad decline is a separate effect, and it splits cleanly.**
Applying the §7 skew-traversal test to the 0.76% spot move:

```
expiry         days  observed  skew explains   residual
2026-08-07        7     -2.56          -1.22      -1.34
2026-08-21       21     -1.51          -0.86      -0.65
2026-10-30       91     -0.67          -0.59      -0.08
2027-06-30      334     -0.20          -0.29      +0.09
```

At 91 days and beyond the residual is under 0.1 vol points — essentially all
measurement effect. At 7 days there is a genuine ~1.3 point decline beyond what
the spot move explains. That is the signature of a market calming after a
turbulent week: near-dated volatility falls while two-year expectations barely
move. Note this is the *opposite* maturity pattern to the event (§7b), which is
why the two are distinguishable.

**The term structure is back to a textbook shape:**

```
  3 days     8.5%
  7 days    11.9%
 14 days    12.5%
 21 days    12.9%
 31 days    13.3%
 61 days    14.3%
 91 days    15.2%
334 days    18.4%
686 days    20.7%
```

Smooth and upward-sloping from three days out to two years, with only the 0DTE
elevated (23.6%, normal for an option with hours to live). Compare the
inverted, humped front end of July 29 in §5. Wing gaps of 0.0–1.6 are the
tightest in the dataset.

**Full arc:** premium builds into the announcement → collapses at 2:00pm →
does not return → term structure normalises within two trading days.

### A cleaner estimator found late

Tuesday 3pm and Wednesday 3pm had nearly identical spot (741.49 vs 742.02,
0.07% apart), so comparing them is free of the skew-traversal problem that
complicates the 1pm/3pm pair. The observed drops at 16/23/30 days were
**0.59 / 0.63 / 0.44** vol points against model predictions of
**0.68 / 0.48 / 0.36** — an independent corroboration of the ±0.95% event size,
using different snapshots than the fit.

**Caveat on signal size.** Those drops are individually *smaller* than the
normal daily fluctuation (sd 1.09–1.49 vol points at these tenors). What gives
them weight is that all five mid-dated tenors moved the same direction with
magnitudes matching a model fitted from other data — not the size of any single
number.

---

## 8. Which data actually produced which result

Worth stating plainly, because the answer is not "all 16 snapshots equally."

| result | snapshots used | count |
|---|---|---|
| The crush (ATM pre vs post) | 07-29 1pm + 3pm | **2** |
| Localization (front vs 2-year) | 07-29 1pm + 3pm | **2** |
| Variance decomposition, event size | 07-29 1pm + 3pm | **2** |
| The 1pm forecast | 07-29 1pm | **1** |
| Superseded 3.1× ratio | 07-29 1pm + 07-28 | 2 |
| Null band | all 13 v1 | 13 |
| Forward-bias diagnosis | 13 v1 + 07-28 | 14 |
| Expiry-ladder bug diagnosis | all 13 v1 | 13 |

**The measurement rests on two snapshots taken two hours apart.** The thirteen
earlier days produced the diagnostics — they are what exposed the ladder bug
and established that the forward bias was persistent and decayed with maturity
— plus the null band, which was inconclusive.

That is not a failure of the collection. Without those thirteen days the two
that mattered would have been uninterpretable: the ladder bug would not have
been visible, and the forward bias would have looked like a one-off glitch
rather than a systematic offset with a diagnosable signature.

Note also that the v1 schema was **not** the constraint. `surface_io`
reconstructs `expiry`, `strike`, `option_type` and `mid` exactly from v1 files;
only `bid`/`ask`/`openInterest` are lost, and no analysis step uses them. All
13 v1 snapshots load and calibrate normally. The constraints were the rotating
ladder and the once-daily cadence.

---

## 9. Expected vs actual

| | expected | actual |
|---|---|---|
| Event premium exists pre-announcement | yes | **partly** — clear at 1pm on 07-29, but *not* consistently visible in the daily snapshots before that |
| Premium collapses at 2:00pm | yes | **yes** — 5–7 vol points at the front |
| Effect localised to short expiries | yes | **yes** — 688-day expiry moved 0.3 pts against a predicted 0.01 |
| Size of the move | ±0.88% (forecast) | −0.671% realized to the close; event component **±0.95%** |
| Only one effect (the event) | yes | **no** — a residual beyond the event exists; §7b shows the front part was post-announcement turbulence that decayed by the next day |
| Premium stays released | assumed | **yes** — 15–30 day expiries within 0.25 pts the next day (§7b) |
| Statistically distinguishable from noise | hoped | **not established** — null band inconclusive, and absent at the front |
| Pre-event build-up trackable day by day | yes | **no** — ladder rotation and daily cadence prevent it |
| Post-event level cleanly observable | assumed | **no** — the 3pm snapshot landed near a transient spike; SPY fell ~12 pts in the next 55 min |

---

## 10. What now

- [x] Keep collecting through early August — the term structure normalising
      over several days is part of the result. **July 30 and 31 confirm the
      crush held and the term structure fully normalised; see section 7b.**
- [ ] README with the hypothesis, the charts, and the honest limitations.
- [ ] Optional: SVI fits per smile; SPY vs a single name (NVDA).
- [ ] **Intraday sampling at the next event.** Hourly through the session
      would resolve the Tuesday-0.48% vs realized-0.95% inconsistency in
      section 7, which once-daily data cannot. Higher value than more days.
- [ ] Optional: repeat at the next FOMC meeting. Two events is not
      significance, but it is the only way this stops being n = 1.

Charts in `charts/`: `term_structure.png`, `crush.png`, `fixed_tenor.png`.
