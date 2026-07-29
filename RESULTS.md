# Results — FOMC event premium, July 2026

A chronological account: what was expected, what was collected, what went
wrong, what was done about it, and what the data actually showed.

Companion to `METHODOLOGY.md`, which explains *why* each step is designed the
way it is. This document is *what happened*.

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

**16 snapshots total, 29,272 rows** (23,120 v1 + 6,152 v2).

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

predicted 3pm ATM IV once event variance is released:
  2026-07-30   28.9% -> 25.1%
  2026-07-31   25.3% -> 22.9%
```

### What happened

**Realized move 1pm → 3pm: +0.964%** (734.93 → 742.02). Inside the predicted
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

**The event was worth roughly ±1% on the day.** Four estimates:

| method | implied move |
|---|---|
| 0DTE direct read (brackets 2pm tightest) | 0.90% |
| **fit restricted to ≤60d (R² = 0.96)** | **1.05%** |
| front cluster (<15 days) | 1.29% |
| fit, all expiries (R² = 0.91) | 1.74% |

The all-expiry intercept is leverage-driven — including the 688-day expiry
alone moves it from 1.05% to 1.74%. The short-dated fit agrees with the direct
reads and is the one to trust.

The 1:00pm forecast of **±0.88%** was slightly low but the right order of
magnitude, and the realized **+0.964%** landed inside the predicted band.

### What is solid

1. **The pre-registered forecast verified out-of-sample.** Written at 1:00pm,
   checked against a 3:00pm outcome.
2. **Localization.** Front expiries fell 5–7 vol points; the 688-day expiry
   fell 0.3. No market-wide shift produces that shape. This is the single
   strongest piece of evidence.
3. **Two effects cleanly separated** — the one-off release and the broad
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

**n = 1.** One meeting is a case study of a known effect, not a statistical
result. Establishing significance needs many event dates.

**Other limitations** carried from `METHODOLOGY.md`: SPY options are American
and Black-Scholes prices European; flat `r` and `q`; calendar-time `T` rather
than trading time; liquidity filters bias toward liquid strikes.

---

## 8. Expected vs actual

| | expected | actual |
|---|---|---|
| Event premium exists pre-announcement | yes | **yes** — front-end inverted, ~3 pts on 07-27, far more by 1pm 07-29 |
| Premium collapses at 2:00pm | yes | **yes** — 5–7 vol points at the front |
| Effect localised to short expiries | yes | **yes** — 688-day expiry moved 0.3 pts |
| Size of the move | ±0.88% (forecast) | ±0.964% realized; event component ~1.05% |
| Only one effect (the event) | yes | **no** — market-wide vol fell too, separable |
| Statistically distinguishable from noise | hoped | **not established** — null band inconclusive, and absent at the front |

---

## 9. What now

- [ ] Keep collecting through early August — the term structure normalising
      over several days is part of the result.
- [ ] README with the hypothesis, the charts, and the honest limitations.
- [ ] Optional: SVI fits per smile; SPY vs a single name (NVDA).
- [ ] Optional: repeat at the next FOMC meeting. Two events is not
      significance, but it is the only way this stops being n = 1.

Charts in `charts/`: `term_structure.png`, `crush.png`, `fixed_tenor.png`.
