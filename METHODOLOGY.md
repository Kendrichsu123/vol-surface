# Methodology

How this project works, end to end: what question it asks, what each stage of
the pipeline produces, and how those outputs combine into an answer.

---

## 1. The question

**Does the options market charge extra for uncertainty it knows is coming, and
does that charge disappear the moment the uncertainty resolves?**

The FOMC announcement on July 29, 2026 at 2:00pm ET is a *scheduled* macro
event. Everyone knows the date in advance. If option prices are forward
looking, options whose lifetime spans July 29 should be more expensive — in
volatility terms — than their maturity alone would justify. And the instant the
statement is released, that extra charge should vanish, because the uncertainty
it was compensating for no longer exists.

Traders call the second half "IV crush." It is the same mechanism that makes
options expensive before an earnings report and cheap the morning after.

Two testable predictions:

1. **Before the event:** the implied-volatility term structure shows a *hump*
   at the expiries bracketing July 29 — they sit above the smooth trend defined
   by their neighbours.
2. **After the event:** that hump collapses and the term structure returns to a
   smooth shape.

---

## 2. Why implied volatility is the right observable

An option price is a number in dollars. It depends on the strike, the time to
expiry, the level of the underlying, and rates — none of which say anything
about uncertainty. What we want is the market's forward-looking estimate of how
much the underlying will move.

Black-Scholes provides the translation. It maps

```
(S, K, T, r, q, sigma)  ->  price
```

and it is strictly increasing in `sigma`. So the map is invertible: given a
market price, exactly one `sigma` reproduces it. That number is the **implied
volatility** — the market's annualised expectation of movement, expressed in a
unit that is comparable across strikes, expiries, and even different underlyings.

**This is not a claim that Black-Scholes is true.** It plainly is not: if it
were, every option on the same underlying would imply the same `sigma`, and
they visibly do not. BS is used here as a *quoting convention* — a
strictly-monotonic dictionary for converting dollars into a normalised measure
of uncertainty. The entire object of study, the volatility surface, is precisely
the pattern of BS's failure. If BS were correct, the surface would be flat and
there would be nothing to look at.

---

## 3. The pipeline, stage by stage

### Stage 1 — The pricer (`main.py`)

**Input:** `S, K, T, r, sigma, q, cp`
**Output:** a theoretical option price

```
d1 = [ln(S/K) + (r - q + sigma^2/2)T] / (sigma * sqrt(T))
d2 = d1 - sigma*sqrt(T)
call = S*e^(-qT)*N(d1) - K*e^(-rT)*N(d2)
put  = K*e^(-rT)*N(-d2) - S*e^(-qT)*N(-d1)
```

Validated three ways in the `__main__` block: a textbook ATM value
(7.9656), put-call parity (`C - P = S*e^(-qT) - K*e^(-rT)`), and a round trip
(price at a known sigma, invert, recover it). These are `assert`s, so a
regression fails loudly.

`bs_delta` is here too — `e^(-qT)*N(d1)` for calls, `-e^(-qT)*N(-d1)` for puts —
because the standard way to quote skew is at equal-and-opposite *delta*, not
equal strike.

### Stage 2 — The inversion (`main.py: implied_vol`)

**Input:** a market price
**Output:** the sigma that reproduces it

There is no algebraic inverse of Black-Scholes in sigma, so this is a
root-find: solve `bs_price(sigma) - market_price = 0` on the bracket
`[1e-6, 5.0]` using Brent's method (a hybrid of bisection and the secant
method — bisection's guaranteed convergence, secant's speed).

**The failure mode is informative.** Brent requires the function to have
opposite signs at the two ends of the bracket. If it doesn't, no volatility in
0.0001%–500% reproduces that price — which means the quote violates a no-arbitrage
bound and is simply bad data. So the solver doubles as a data-quality filter,
and rejects are counted per expiry rather than silently swallowed.

### Stage 3 — Market data and cleaning (`data.py: smile_for_expiry`)

**Input:** a ticker and an expiry date
**Output:** one expiry's smile — IV as a function of strike

Raw chains are dirty. Four decisions do the cleaning:

| Decision | Why |
|---|---|
| **Mid price** `(bid+ask)/2`, not last | Last trade can be hours stale; mid reflects where the market is *now* |
| **OTM only** (puts below spot, calls above) | Deep ITM options are wide, illiquid, and mostly intrinsic value — their prices carry almost no volatility information. This is the CBOE/VIX convention |
| **`bid > 0`, `spread/mid < 0.5`, `openInterest > 0`** | Removes quotes so wide the mid is meaningless, and strikes nobody actually trades |
| **Reject un-invertible quotes** | Arbitrage violations (see Stage 2) |

Assumptions: `r = 0.045` (T-bill), `q = 0.012` (SPY dividend yield), both flat.

`T` is a fraction of a year measured to 4:00pm ET on the expiry date. Calendar-day
resolution would give `T = 0` for a same-day expiry, dividing by zero in `d1` —
and on FOMC day the 0DTE contract is the most information-rich one on the board.

### Stage 4 — Normalisation

**Input:** strikes in dollars
**Output:** log-moneyness `ln(K/S)`

A $700 strike is deep out-of-the-money for a one-week option and nearly
at-the-money for a one-year option. Raw strikes are therefore not comparable
across expiries. Log-moneyness re-centres every expiry on zero (= at-the-money)
and expresses distance in proportional terms, which makes smiles from different
maturities directly comparable — and makes the surface a genuine surface rather
than a pile of unrelated curves.

### Stage 5 — The expiry ladder (`data.py: select_expiries`)

**Input:** all listed expiries
**Output:** ~14 expiries spanning one day to two years

Expiries are chosen as the nearest listed date to each of
`[1, 3, 7, 14, 30, 60, 90, 180, 365, 730]` days, plus a hard-coded list of the
FOMC-bracketing dates.

This is **date-anchored, not index-anchored**, and that distinction is the
single most important structural decision in the collection code. Selecting by
list position (`spy.options[:40:3]`) seems equivalent but is not: as expiries
roll off the front, the list shifts under you and the stride lands on different
dates each day. In the first 13 snapshots that produced 41 distinct expiries,
with no single expiry present in more than 6 of them — making it impossible to
track one contract through the event. See `notes.md` for the full diagnosis.

### Stage 6 — The surface and the archive

**Input:** all selected expiries
**Output:** one CSV per snapshot

Stacking every expiry's smile gives IV as a function of two variables —
log-moneyness and time — which is the volatility surface. `save_daily_surface`
writes it to `data/surface_YYYY-MM-DD.csv` with `spot`, `snapshot_date`, and
`snapshot_ts` stamped on every row.

The stored columns are deliberately wider than the analysis strictly needs
(`strike`, `option_type`, `delta`, `bid`, `ask`, `mid`, `openInterest`). The
reason is that you cannot re-query a historical option chain — yfinance serves
only the live book. **Every snapshot is a one-shot observation.** Anything not
saved at 3pm is gone forever, so the archive stores enough to re-derive
quantities later, including ones not yet anticipated. This is what makes the
forward-calibration correction in §6 possible after the fact.

---

## 4. What gets measured

Two numbers per expiry per snapshot.

### ATM implied volatility → the term structure

Interpolate IV to `log_moneyness = 0`. Plotting ATM IV against `T` gives the
**term structure**: the market's expected volatility over each horizon.

Normally it slopes gently upward and is smooth, because each expiry's horizon
overlaps almost entirely with the next. A *kink* is therefore meaningful — it
says the market expects something specific to happen in the gap between two
expiries.

### 25-delta skew → the shape

`IV(25-delta put) - IV(25-delta call)` for each expiry.

Quoted at equal delta rather than equal strike so that the two wings are
equally far out-of-the-money in probability terms, which keeps the measure
comparable across expiries with different volatilities. It captures whether the
market's fear is *directional* (crash protection) rather than just elevated.
An event can move the level, the shape, or both — measuring only ATM would miss
half the story.

---

## 5. The identification strategy

The critical methodological question: **if the FOMC expiry shows high IV, how
do you know that's the event and not just something about short-dated options?**

The design answers this with a **difference-in-differences**, using two
independent comparisons:

**Comparison A — across expiries, same day.** Compare the event-spanning expiry
to its immediate neighbours in the same snapshot. Both are priced at the same
instant, under the same market conditions, on the same underlying. Any
market-wide shift in volatility hits both equally and cancels. What remains is
specific to spanning July 29.

**Comparison B — across time, same expiry.** Compare that expiry against itself
before and after 2:00pm on July 29. Anything permanently characteristic of the
contract — its maturity, its liquidity, its position on the smile — cancels.

Neither alone is conclusive. Comparison A could reflect a term-structure quirk;
Comparison B could reflect the market simply calming down. **Their interaction
is the result:** an excess that is present in A before the announcement and
absent in A after it can only plausibly be the event.

Concretely, the estimator is:

```
E(t) = ATM_IV(event expiry, t) - [smooth term structure fitted to
                                  non-event expiries, evaluated at that T]

crush = E(pre-announcement) - E(post-announcement)
```

`E(t)` is the **event premium**: the residual after removing the normal
term-structure shape. The prediction is `E > 0` before 2pm on July 29, `E ~ 0`
after, and `crush > 0`.

### Why the pre/post pair is same-day

The pre snapshot is 1:00pm and the post is 3:00pm on July 29 — **two hours
apart, not a day**. This matters more than it looks:

- `T` is essentially unchanged, so nothing has to be adjusted for time decay
- The expiry ladder is identical
- Spot has barely moved, so "at-the-money" means the same strike
- No overnight gap, no weekend, no other news cycle

A day-over-day comparison would confound the crush with a full session of
unrelated movement. Two hours astride the announcement isolates it about as
cleanly as public data allows.

---

## 6. Known bias: forward misspecification

**This is the main data-quality caveat and it must be stated in any writeup.**

Put and call IVs should agree where the wings meet at the money. In this data
they systematically do not. On the July 28 10:04am snapshot, the 737 put implied
33.3% while the 738 call implied 20.4% — one strike apart.

That gap is not noise; it is an arbitrage violation. Put-call parity off those
quotes gives `C(737) = 2.77` against an observed `C(738) = 1.295`, implying a
one-point vertical spread worth $1.48 when its ceiling is $1.00.

**Cause:** the spot price and the option chain come from different feeds with
different timestamps. Solving for the forward that reconciles the two wings
gives ~736.35 against the 737.40 used — the spot is roughly 1 point stale.

**Signature:** the gap decays with maturity, exactly as a forward error must
(the same dollar error is a smaller fraction of a wider distribution). A real
market feature would not behave this way. Measured on the July 27 snapshot:

| expiry | days | put ATM | call ATM | gap |
|---|---|---|---|---|
| 2026-07-30 | 3 | 22.4% | 17.0% | +5.4 |
| 2026-08-04 | 8 | 18.0% | 14.8% | +3.2 |
| 2026-08-28 | 32 | 16.4% | 15.1% | +1.3 |
| 2027-06-30 | 338 | 19.2% | 18.9% | +0.2 |

**Magnitude.** A 1.05-point spot error moves ATM IV by ~8.8 points at 0DTE,
~2.6 points at 2 days, ~0.75 at 24 days.

**Mitigations, in increasing order of rigour:**

1. **Average the two wings.** The error is antisymmetric — it inflates puts and
   deflates calls by roughly equal amounts — so `(put_ATM + call_ATM)/2` cancels
   it to first order. Cheap and effective.
2. **Note that it partly cancels in the difference.** The crush is a difference
   of two ATM readings taken two hours apart, both biased in the same direction,
   so much of the error subtracts out.
3. **Calibrate the forward per expiry.** Solve for the `F` that makes the two
   wings agree, then re-invert every quote against it. This is the correct fix
   and is possible offline because `strike`, `option_type`, `mid`, and `spot`
   are all stored. Not yet implemented.

**This bias revised the headline number.** An initial reading of the July 27
snapshot interpolated across both wings and reported a ~4.3 vol-point hump at
the event expiry. Wing-averaging gives **~3 points** (19.7% at 3 days against
16.4% and 16.7% behind it). The effect is real; the first estimate was inflated
by the put wing.

---

## 7. Converting the hump into something interpretable

A "3 vol point hump" is hard to intuit. It can be turned into a number anyone
understands: **how big a move is the market pricing for FOMC day?**

Volatility scales as variance × time, so total variance to expiry is `sigma^2 * T`.
For the event-spanning expiry, the pre-announcement total variance contains the
event; the post-announcement total variance does not. Because the two snapshots
are only two hours apart, `T` is effectively the same in both, so:

```
v_event  ~=  T * (sigma_pre^2 - sigma_post^2)

implied event move  =  sqrt(v_event)
```

Worked example with plausible numbers — if the July 31 expiry (`T = 2/365` on
July 29) shows 20% pre and 13% post:

```
v_event = (0.20^2 - 0.13^2) * (2/365) = 1.27e-4
sqrt    = 0.0113  ->  the market was pricing a +/-1.1% move on FOMC day
```

That is a single sentence a non-specialist understands, derived entirely from
this pipeline. It is an approximation — some ordinary variance also elapses
between 1pm and 3pm, and it assumes the whole IV change is attributable to the
event — but it is the standard desk calculation.

---

## 8. Limitations

- **n = 1.** One FOMC meeting is a case study of a known effect, not a
  statistical result. Establishing significance needs many event dates. This
  should be stated plainly rather than hedged around.
- **Forward misspecification** (§6) — quantified and partly correctable, but
  present in every snapshot.
- **American vs European.** SPY options are American; Black-Scholes prices
  European. The early-exercise premium is small for short-dated OTM options, but
  it is an approximation. `^SPX` options are European if purity matters later.
- **Flat `r` and `q`,** not term structures or forward-implied values.
- **One snapshot per day** (two on July 29). Day-over-day resolution only; the
  intraday dynamics of the surface are invisible.
- **`T` uses calendar time to 4pm,** not trading time. Volatility accrues during
  sessions, not over weekends, so calendar-time `T` slightly misstates
  short-dated options across weekends.
- **Survivorship in the filters.** Requiring `openInterest > 0` and
  `spread/mid < 0.5` biases toward liquid strikes, which thins the wings —
  particularly the far-dated deep-OTM put wing, the least reliable region of
  the surface.

---

## 9. What the data has shown so far

Observations from the collected snapshots, independent of the FOMC result:

- **Equity skew.** Deep OTM puts imply ~52% vol against ~13% ATM on short
  maturities. Downside protection is expensive in volatility terms — the
  crash-insurance premium, a permanent feature since 1987.
- **Skew flattens with maturity.** Short-dated smiles are steep; long-dated
  smiles are gentle. Visible in both the 3D surface and the heatmap.
- **The volatility trough sits slightly above spot,** near the forward, not
  exactly at spot.
- **The put wing survives filtering better than the call wing** — more open
  interest in downside protection.
- **The data region is triangular.** Near-dated options only list strikes close
  to spot; far-dated options span enormous ranges. Available strike width grows
  roughly with `sqrt(T)`. The white space in the heatmap is "no options exist
  there," not missing data.
- **Validation.** Computed IVs match yfinance's own within ~1 vol point. The
  residual is consistent with the forward misspecification in §6.

---

## 10. Pipeline summary

```
yfinance option chain
        |
        v
  filter: OTM, bid>0, spread/mid<0.5, OI>0        <- liquidity
        |
        v
  mid price = (bid+ask)/2                          <- dollars
        |
        v
  brentq root-find on Black-Scholes                <- dollars to sigma
        |                                             (rejects bad quotes)
        v
  IV per strike per expiry
        |
        v
  normalise: log-moneyness, T in years, delta      <- comparable across expiries
        |
        v
  stack expiries -> the volatility surface
        |
        v
  daily CSV snapshot (one-shot; unrepeatable)
        |
        v
  extract: ATM IV per expiry, 25-delta skew
        |
        v
  difference-in-differences across expiry x time
        |
        v
  event premium E(t), crush = E(pre) - E(post)
        |
        v
  implied FOMC-day move = sqrt(T*(sigma_pre^2 - sigma_post^2))
```
