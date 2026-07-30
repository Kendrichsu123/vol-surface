# Explainer — the project, in order, explained from scratch

Written for someone with no options background. Every number is from this
project's real data, and every calculation is shown.

## How to read this

The document has four parts, and each section is tagged with the job it does:

| tag | meaning |
|---|---|
| **CONCEPT** | Background. Not a finding — just a tool you need before the story makes sense. Each one says which later step it's needed for. |
| **WHAT I DID** | An actual step of the project, in chronological order. |
| **PROBLEM** | Something that went wrong, and what was done about it. |
| **FINDING** | A result. What the data actually said. |
| **REVISED** | A number I reported earlier and later downgraded, with the reason. |

```
PART A  concepts        the toolkit — no results here
PART B  the story       July 9 to July 29, in order
PART C  the findings    what the data said, and how much to trust it
PART D  glossary
```

Companion documents: `METHODOLOGY.md` (why the design is what it is),
`RESULTS.md` (the formal record with all numbers).

## The answer, up front

> The options market charged extra for the Fed announcement of July 29, 2026,
> and that extra disappeared the moment the announcement landed.
>
> **Size: about ±0.95%** — the move the market priced for the event itself.
> (A point estimate with real uncertainty: methods range roughly 0.5%–1.1%.
> See C5.)
> **It was the event, not the market:** expiries 1–2 days out fell 5–7
> volatility points in two hours, while the 2-year expiry moved 0.3.
> **It stuck:** the next day's snapshot showed the mid-dated expiries within
> 0.25 points of where the announcement left them.
>
> One meeting, so this is a quantified case study of a known effect, not a
> statistical result.

Everything below explains how each of those numbers was arrived at.

---

# PART A — Concepts

*Nothing in this part is a result. It's the vocabulary and the math you need
before Part B means anything.*

## A1 · CONCEPT — What an option is

An **option** is insurance on a stock: the right, but not the obligation, to
trade at a fixed price on a fixed date.

- **Call** — the right to *buy* at a fixed price. Pays off if the stock rises.
- **Put** — the right to *sell* at a fixed price. Pays off if the stock falls.
- **Strike (K)** — the fixed price in the contract.
- **Expiry (T)** — when the contract dies. SPY options expire at 4:00pm ET.
- **Spot (S)** — the stock's price right now.
- **Premium** — what the option costs.

**SPY** is a fund tracking the S&P 500. At 735, that's $735 a share, with
options at strikes like 730, 735, 740.

| term | meaning | example (spot = 735) |
|---|---|---|
| **at-the-money (ATM)** | strike ≈ spot | 735 |
| **out-of-the-money (OTM)** | worthless if exercised now | 750 call, 720 put |
| **in-the-money (ITM)** | worth something now | 720 call, 750 put |

**0DTE** = expiring today.

*Used in:* everything. Also explains one design choice — this project uses
**only OTM options**, because ITM options are mostly just their guaranteed
value (a 720 call with spot at 735 is worth at least $15 regardless), so their
prices say little about uncertainty. OTM options are pure uncertainty.

## A2 · CONCEPT — The question the whole project is testing

The Fed announced interest rates on **Wednesday July 29, 2026 at 2:00pm ET.**
Everyone knew the date weeks ahead.

If options are insurance, insurance covering a *known upcoming risk* should
cost extra — and should get cheap the instant the risk passes. So:

1. **Before 2:00pm:** do options spanning July 29 cost more than their length
   alone justifies?
2. **After 2:00pm:** does that extra vanish?

Everything below exists to answer those two questions.

## A3 · CONCEPT — Turning a price into "expected movement"

*Needed for: every measurement in this project.*

A 740 call costing $2.10 tells you almost nothing on its own. Is that
expensive? Depends on the strike, the time left, and where the stock is.

**Volatility** is how much a stock tends to move, quoted as an annual
percentage. "20% volatility" means one standard deviation of movement over a
year is 20%.

The **Black-Scholes formula** takes six inputs and returns a fair price:

```
(spot, strike, time, interest rate, dividend yield, volatility) -> price
```

Five are known. Only volatility isn't. So run it **backwards**: given the
market's actual price, find the volatility that reproduces it. That's the
**implied volatility (IV)** — the market's forecast of future movement, backed
out of what people are paying.

**"Implied"** means *implied by the price* — not measured from history. It's a
forecast, not a measurement.

### Why running it backwards needs a search

Black-Scholes can't be rearranged to solve for volatility; it's buried inside a
function with no closed-form inverse. So the solver guesses and narrows:

> 5% gives $0.40 — too low. 60% gives $4.20 — too high. 30% gives $2.05 —
> close. Try 32%…

That's **Brent's method**, and it converges in a few dozen steps.

**Its failure is informative.** If *no* volatility between 0.0001% and 500%
reproduces the price, that price is impossible — it breaks a basic
no-arbitrage rule. So the solver doubles as a bad-data detector.

### Worked example

*"On July 28 at 10:04am, SPY was at 737.40. A put at strike 737 expiring 4pm
that day was quoted at $2.355. Running Black-Scholes backwards on that price
gives 33.3%."*

Note: the option had ~6 hours left, but **33.3% is still per year**. Always
annualised, so different maturities are comparable. A4 converts it back.

## A4 · CONCEPT — The √T rule

*Needed for: the forecast in B5.*

To convert annual volatility into an expected move over a shorter window, scale
by the **square root** of time:

```
expected move over period T  =  sigma * sqrt(T)
```

**Why square root?** Stock moves are roughly independent day to day. When you
add independent random quantities their **variances** add, not their standard
deviations. Volatility is a standard deviation, so it grows with √time.

A day of ±1% doesn't make four days ±4%. It makes ±1% × √4 = **±2%** — some
days go up, some down, and they partly cancel.

## A5 · CONCEPT — Variance, the quantity that actually works

*Needed for: B7 and every finding in Part C. This is the most important idea
in the project.*

**Total variance = volatility² × time**, written `V = sigma^2 * T`.

> **Variance adds up over time. Volatility does not.**

You can't subtract a 3-day volatility from an 8-day volatility to get "the
volatility of the 5 days between" — meaningless. But you *can* subtract total
variances, and the answer is exactly what the market charges for those days:

```
variance of the window between two expiries  =  V(T2) - V(T1)
```

This is **forward variance**. It's what lets you isolate a *single day* instead
of vaguely saying "the front end looks high." Convert back with a square root:

```
implied move over a window  =  sqrt(variance of that window)
```

## A6 · CONCEPT — The forward, and put-call parity

*Needed for: the problem found in B4 and the correction in B7.*

The **forward price (F)** is the price for delivery later rather than today. It
differs from spot because paying later earns you interest (pushes F up) and
forgoes dividends (pushes F down):

```
F = S * e^((r - q) * T)
```

Over 3 hours that's negligible; over two years it's several percent. **The
forward, not spot, is the true centre of the options market.**

**Put-call parity** links a call and a put at the same strike:

```
C - P = S*e^(-qT) - K*e^(-rT)
```

**Why it must hold:** buy a call and sell a put at the same strike K. If the
stock ends above K you exercise the call and buy at K. If it ends below, the
put is exercised against you and you buy at K. Either way you buy at K — which
is exactly a forward contract, so it must cost the same. Otherwise you could
buy the cheap version, sell the expensive one, and pocket risk-free profit.

**This is not a model.** Black-Scholes could be entirely wrong and parity would
still hold, because it follows from the payoffs alone. That's what makes it a
trustworthy auditing tool — and it's what caught the bug in B4.

---

# PART B — The story, in order

## B1 · WHAT I DID — Built the tools (before July 9)

Wrote the Black-Scholes pricer (A3), then the inverter using Brent's method,
then the data pipeline: pull SPY's option chain, filter it, convert every price
to implied volatility.

Four filtering decisions:

| decision | why |
|---|---|
| mid price `(bid+ask)/2` | the last traded price can be hours stale |
| OTM only | ITM options are mostly intrinsic value (A1) |
| `bid > 0`, `spread/mid < 0.5`, `openInterest > 0` | drop untradeable quotes |
| log-moneyness `ln(K/S)` | makes different expiries comparable |

Two bugs surfaced here, both from `notes.md`:

- `puts["bid"] + calls["ask"]` for the put mid — a copy-paste error that ran
  silently and produced wrong numbers. Caught only by benchmarking against an
  independent source.
- `spy.options[:12]` returned the 12 *nearest* expiries; SPY has daily
  expiries, so all 12 landed within three weeks. Changed to `[:40:3]`.

**That second "fix" contained the bug that later mattered most (B3).**

## B2 · WHAT I DID — Collected daily (July 9–27)

A scheduled job ran every trading day at 3:00pm ET: ~1,700 option contracts per
day, 9–11 expiries spanning tomorrow to two years out. **13 snapshots.**

One irregularity: July 15 ran at 3:45pm after a wifi outage.

## B3 · PROBLEM — The expiry ladder was rotating (found July 27)

`spy.options[:40:3]` picks expiries by **position in a list**, not by date. As
old options expire, the list shifts, so "every third one" lands on different
dates each day.

**Measured: 41 different expiries across 13 days, and no single expiry
appearing in more than 6 of them.** The July 31 expiry — an obvious one to
track through the event — was missing from the entire final week.

*Analogy:* trying to time one song when your stopwatch only records at random
5-minute intervals. The song is in there, mixed with everything around it.

**Fixed** by choosing expiries by *target date* (nearest to 1, 3, 7, 14, 30,
60, 90, 180, 365, 730 days) plus a forced list of dates bracketing July 29.

**Two days before the event.** Any later and the measurement would have been
unusable.

## B4 · PROBLEM — The stock price and option prices disagreed (found July 28)

A manual 10:04am run showed the **737 put implying 33.3%** and the **738 call
implying 20.4%** — one strike apart. That's impossible for genuine quotes.

Using parity (A6) to work out what a 737 *call* must cost:

```
C(737) = 2.355 + 737.40*e^(-0.012*0.00068) - 737*e^(-0.045*0.00068)
       = 2.355 + 737.3940 - 736.9774
       = 2.7715
```

Compare to the observed 738 call at $1.295:

```
C(737) - C(738) = 2.7715 - 1.295 = 1.4765
```

**That cannot be right.** Buy the 737 call, sell the 738. At expiry that pays
**at most $1.00** — the gap between strikes. Above 738 the two offset; below
737 both expire worthless. So it can never be worth more than $1.00, yet it
costs $1.4765. Anyone could sell it and keep $0.47 risk-free.

**Markets don't leave free money lying around.** So the conclusion isn't "free
money" — it's **"my inputs are inconsistent."** The spot price came from one
data feed and the option quotes from another, timestamped seconds apart.
Solving for the forward that reconciles both wings gives **≈736.35** — the spot
was about **1 point stale**.

### Why this makes puts look expensive and calls look cheap

A too-high spot makes every put look further out-of-the-money than it is, so
the solver needs more volatility to explain its price — **put IVs inflate**.
Calls are the mirror image — **call IVs deflate**. Exactly the observed pattern.

### The fingerprint that confirmed it

A 1-point error on 735 is 0.14% of the price. For a 3-day option, whose whole
range of outcomes is ~2% wide, that's a big chunk. For a 338-day option, ~19%
wide, it's nothing. So the error **must shrink with maturity**:

| expiry | days | put ATM | call ATM | gap |
|---|---|---|---|---|
| 2026-07-30 | 3 | 22.4% | 17.0% | **+5.4** |
| 2026-08-04 | 8 | 18.0% | 14.8% | +3.2 |
| 2026-08-28 | 32 | 16.4% | 15.1% | +1.3 |
| 2027-06-30 | 338 | 19.2% | 18.9% | **+0.2** |

A real market feature wouldn't fade like that. **The decay is what turned a
guess into a diagnosis.**

**Decision:** don't touch the collector the day before an unrepeatable event.
The saved columns were enough to correct this afterwards (B7).

## B5 · WHAT I DID — Wrote a forecast at 1:00pm on July 29

One hour before the announcement, using only data that existed at that moment.

The option expiring at 4pm that day had ATM implied volatility of **58.0%**.
Applying A4:

```
T = 3 hours = 3/8760 years = 0.00034247
sqrt(T) = 0.018506
move = 0.580 * 0.018506 = 1.07%     ->  +/- 7.88 points on SPY at 734.93
```

**±1.07%** is *one standard deviation* — about a 68% chance of landing inside.
Not a maximum, and the sign is unknown.

Written down **before** the outcome, so it couldn't be adjusted afterwards.

## B6 · WHAT I DID — Took the post-announcement snapshot at 3:00pm

Two hours later. Same day, same expiries, so nothing needs adjusting for the
passage of time.

```
expiry        days   ATM 1pm   ATM 3pm   change
2026-07-29     0.1     58.0%     54.9%     -3.2
2026-07-30     1.1     28.9%     22.1%     -6.8
2026-07-31     2.1     25.3%     19.7%     -5.6
2026-08-07     9.1     18.2%     15.5%     -2.7
2026-08-21    23.1     16.8%     14.4%     -2.4
2027-06-30   336.1     18.7%     18.2%     -0.5
2028-06-16   688.1     21.0%     20.7%     -0.3
```

**Realized move: +0.964%** (734.93 → 742.02), inside the predicted band.

## B7 · WHAT I DID — Cleaned and analysed

**Reconciled two file formats.** The July 9–27 files stored fewer columns. All
the missing pieces rebuild exactly — expiry date, strike, put-or-call, and the
option's price all re-derive from what was saved. Only bid/ask/open-interest
are truly gone, and nothing in the analysis uses them.

**Corrected the forward bias from B4 properly.** For each expiry, search for
the forward price `F` that makes the put and call wings agree, then re-price
everything against it. This succeeded on **135 of 175** expiries. Where it
failed, the fallback is *wing-averaging* — since the error pushes puts up and
calls down by roughly equal amounts, averaging the two cancels most of it.

---

# PART C — The findings

## C1 · FINDING — The event was worth about ±0.95%

An event is a **fixed chunk of variance** sitting inside every option that
spans it. When the announcement happens, that chunk is released. Fitting:

```
dV(T)  =  a  +  b*T
```

- **`a`** — a constant amount released regardless of maturity → **the event**
- **`b*T`** — grows with maturity → **a market-wide change in ordinary vol**

Using **only** the 10 expiries where the forward correction succeeded in both
snapshots:

```
calibrated, <=30d    n=5    a = 9.04e-5  ->  0.95%    R2 = 0.996
calibrated, <=60d    n=6    a = 1.27e-4  ->  1.13%    R2 = 0.940
calibrated, all      n=10   a = 2.95e-4  ->  1.72%    R2 = 0.950
```

> **Headline: the market priced the Fed announcement at about ±0.95% of SPY
> movement.** It uses none of the contaminated short-dated data.

Treat that as a point estimate, not a tight number. Other defensible methods
give 0.5%–1.1% — see C5 §3 for why, and for the one comparison that suggests
±0.95% may sit at the high end of the plausible range.

**How much weight to put on R² = 0.996.** It means the five points sit almost
exactly on the fitted line. But the line was fitted *to those same five
points*, so this is an **in-sample** measure — a statement that the data is
well-behaved, not a test of the model. With 5 points and 2 parameters, almost
any smooth relationship would fit this well. The genuine out-of-sample test in
this project is the 1:00pm forecast in B5, which was written before the
outcome existed. Keep the two separate.

**Why the all-expiry number is higher and shouldn't be used.** Least squares
minimises squared error, so a point far from the rest dominates. The 688-day
expiry has ~50× the variance of the front ones, so it dictates the line and
drags the estimate from 1.13% to 1.72% single-handedly. That's **leverage** —
and that expiry didn't even pass the forward correction.

## C2 · FINDING — It was the Fed, not the market

*The obvious objection: maybe the whole market just calmed down that
afternoon.*

Since `V = sigma^2 * T`, removing a fixed variance chunk Δ drops volatility by:

```
drop  ~  delta / (2 * sigma * T)
```

**The `T` in the denominator is the entire argument.** The same fixed chunk is
a huge fraction of a short option and a trivial fraction of a long one. Using
the fitted Δ:

| expiry | predicted event drop | **observed drop** |
|---|---|---|
| 2026-07-30 | 6.67 pts | **6.8** |
| 2026-07-31 | 3.73 pts | 5.6 |
| 2026-08-21 | 0.52 pts | 2.4 |
| 2028-06-16 | **0.01 pts** | **0.3** |

Two readings:

**The front matches almost exactly** — 6.67 predicted against 6.8 observed.

**The 2-year expiry is the control.** The Fed should have moved it by **0.01
vol points** — invisible. It moved 0.3. So that 0.3 **can't be the Fed**.

A market-wide calming pushes *everything* down together. An event crushes the
front and leaves the back alone. **Observed: 6.8 at the front, 0.3 at the back.
Only an event does that.**

## C3 · FINDING — The event alone doesn't explain the whole drop

*This section raises a problem. C6 resolves it.*

The event explains the front of the curve well, but not the middle and back:

```
expiry         days   observed drop   event explains   left over
2026-07-31      2.1        5.60            3.12          2.48
2026-08-07      9.1        2.70            1.00          1.70
2026-08-21     23.1        2.40            0.43          1.97
2026-10-30     93.1        1.00            0.11          0.89
2028-06-16    688.0        0.30            0.01          0.29
```

At 23 days the event accounts for 0.43 of a 2.40-point drop. Something else did
most of the work.

### Most of it is the stock price moving, not volatility falling

SPY rose 0.96% between the two snapshots (734.93 → 742.02).

"At-the-money volatility" means *the volatility at whatever strike the stock
currently sits at*. When the stock moves, that's a **different strike** — and
because of skew (A1), different strikes carry different volatilities, with
lower strikes always more expensive.

So a rally slides your measurement point rightward, down the skew. **ATM
volatility reads lower even if not a single option's price changed.**

Here is the test. The skew slope says how steep the hill is at each maturity;
multiply by the 0.96% move to get the predicted slide:

```
expiry          skew slope   predicted from    left over
                             the spot move     (from above)
2026-07-31          -2.52        -2.42            2.48
2026-08-07          -1.90        -1.82            1.70
2026-08-21          -1.47        -1.41            1.97
2026-10-30          -0.96        -0.92            0.89
2027-06-30          -0.43        -0.42            0.47
2028-06-16          -0.16        -0.16            0.29
```

**Those two columns match almost expiry for expiry.**

### Why it shrinks with maturity

The skew slope falls from −2.52 at two days to −0.16 at two years: **skew
flattens as you look further out.** Over a single day a crash is a dramatic
tail event that dominates the shape of the distribution, so downside protection
is far more expensive than upside. Over two years, crashes and recoveries
average out and the two wings price much closer together.

Since the slide is `slope × spot move`, a flatter hill means a smaller slide.
That is why the leftover shrinks from ~2.5 points at the front to ~0.3 at two
years — **and why it initially looked like "a market-wide volatility decline
that decays with maturity."** It has that shape because *skew* has that shape.

### How much of it is real?

Genuinely unresolved:

- If the smile is **fixed in strike space**, nothing got cheaper — you measured
  a different option. Pure measurement effect.
- If the smile **travels with spot**, ATM volatility really did fall.

Real markets sit between, and **one event with one spot move cannot tell you
where.** Recorded as a limitation rather than resolved.

The accurate statement: *the extra drop is mostly explained by the spot move,
and how much counts as a genuine volatility change is not determinable from
this data.*

**An earlier version of this section called the leftover "a market-wide
volatility decline."** That was asserted before the spot move was tested, and
it was wrong to state it as a finding.

## C4 · REVISED — Why the 0DTE expiry is excluded, and what that retracted

Converting price → volatility becomes hypersensitive as expiry approaches. With
hours left, a tiny error in the stock price produces an enormous error in
volatility — like measuring someone's height mid-jump.

The 0DTE expiry (the one expiring that same afternoon) shows exactly that:

- the largest put/call inconsistency anywhere in the data (**+30** vol points
  at 1pm, **+38.5** at 3pm — see B4 for what that gap means)
- **the forward correction failed on it entirely**, in both snapshots
- it implies more variance for 3 hours than July 28's data priced for the whole
  of Wednesday (1.07% vs 1.015%), which cannot both be true

**So it is excluded from C1**, and anything resting on it was withdrawn:

| withdrawn | value | status |
|---|---|---|
| "3.1× a normal 3-hour window" | 3.1× | upper bound, not a measurement |
| "0DTE direct read" | 0.90% | superseded by C1's ±0.95% |
| front cluster (<15 days) | 1.29% | superseded by C1's ±0.95% |

The 1:00pm forecast in B5 also used the 0DTE, so **its accuracy is partly
luck** — though it did land close to C1's answer.

## C5 · FINDING — What's weak, stated plainly

Four limitations. Two were caused by the expiry-ladder bug (B3) and would not
recur now that it's fixed; two need more data than one event can provide.

### 1. No consistent premium visible before the event *(fixable — caused by B3)*

Measuring the variance rate of the window bracketing July 29 in each daily
snapshot, against a comparable baseline:

```
07-09   9 trading-day window   0.90x
07-14   7                      0.97x
07-17   4                      1.15x
07-20   3                      1.33x
07-21   3                      0.80x
07-23   3                      1.37x
07-28   1                      1.07x
```

Most sit below 1.0. The build-up isn't visible day by day because the rotating
ladder rarely gave expiries on *both* sides of July 29 — so the single event
day is smeared across a 3-to-9-day window and diluted. With the fixed ladder,
every day would bracket it within one trading day, as July 28 does.

### 2. The noise test is inconclusive *(partly fixable — caused by B3)*

The crush is only 1.3–1.7× a normal day's fluctuation at 10–60 day maturities.
Worse, it **can't be computed at 1–2 days where the effect actually is**,
because the rotating ladder almost never listed expiries that short. There is
no baseline at the front.

### 3. Tuesday said 0.48%, Wednesday released 0.95% *(needs intraday sampling)*

This one is worth spelling out, because it's the sharpest open question.

On **Tuesday at 3pm**, the market's own prices said Wednesday would be worth
about **0.48%** *more* than an ordinary day. That comes from comparing the
expiry that dies Tuesday against the one that dies Wednesday — the gap between
them is exactly what the market charges for Wednesday, and stripping out a
normal day's worth leaves 0.48%.

On **Wednesday**, the crush released about **0.95%**.

Those should match. The event premium the market charged on Tuesday ought to
equal what got released when the event happened. Roughly double is a real
discrepancy. Three candidate explanations:

- **The premium grew.** Volatility often builds into an event as positioning
  concentrates. Tuesday afternoon may simply have under-priced what Wednesday
  lunchtime believed.
- **The 0.95% is somewhat overstated.** C3 showed the spot move inflates the
  measured drop. Correcting for it lowers the estimate toward **0.62%** — much
  closer to Tuesday's 0.48%. That's weak evidence the true figure sits below
  the headline.
- **Both.**

**Once-a-day sampling cannot distinguish these**, because the entire build-up
happened between two snapshots. Hourly sampling through the day would show the
premium's path directly. This is the single strongest argument for intraday
collection at a future event.

Practically: treat **±0.95% as a point estimate with real uncertainty around
it**, roughly 0.5% to 1.1% depending on method, rather than a tight number.

### 4. n = 1 *(needs more events)*

One meeting is a quantified case study of a known effect, not a statistical
result. Nothing here establishes that this happens *reliably* — only that it
happened this time, by this much, with this shape. A second and third FOMC
meeting is the only fix.

## C6 · FINDING — Did the crush stick? (July 30)

*This is the section that resolves C3.*

The day after the announcement gives a clean test, because spot moved only
**−0.17%** overnight — so none of the skew-traversal ambiguity from C4 applies.

```
expiry         days      Tue      Wed      Thu   Wed->Thu
2026-07-31      1.0    19.4%    19.7%    17.6%     -2.13
2026-08-04      5.0    15.5%    14.7%    13.0%     -1.77
2026-08-07      8.0    15.8%    15.4%    14.5%     -0.89
2026-08-14     15.0    15.3%    14.7%    14.5%     -0.23
2026-08-21     22.0    15.1%    14.4%    14.5%     +0.03
2026-08-28     29.0    15.2%    14.8%    14.9%     +0.12
2027-06-30    335.0    18.9%    18.6%    18.6%     +0.05
```

**Two clean results.**

**The event release was permanent.** At 15–30 days — where the clean signal
lives — Thursday sat within 0.25 points of Wednesday. It did not climb back
toward Tuesday's 15.1%. The premium came out and stayed out.

**The front's extra elevation was turbulence, and it decayed.** The 1–8 day
expiries fell a *further* 0.9–2.1 points. Those expiries had been high on
Wednesday not because of the Fed but because the market was moving violently
(SPY swung 730–743 that afternoon). Once it settled, they came down.

**So the two components separate by their behaviour over time**, which is
better evidence than the regression in C1: an event release is permanent, a
turbulence premium is not. This is what C3 was groping toward with the label
"market-wide decline," which was the wrong name for it.

**Data quality also returned to normal.** Thursday's put/call wing gaps were
0.2–2.6 points against Wednesday's 5–8, confirming those wide gaps were the
fast market rather than anything wrong with the pipeline.

## C7 · FINDING — Which data produced which result

| result | snapshots used | count |
|---|---|---|
| The crush | 07-29 1pm + 3pm | **2** |
| Localization (C2) | 07-29 1pm + 3pm | **2** |
| Event size (C1) | 07-29 1pm + 3pm | **2** |
| The 1pm forecast | 07-29 1pm | **1** |
| Noise test | all 13 early days | 13 |
| Forward-bias diagnosis (B4) | 13 early + 07-28 | 14 |
| Ladder-bug diagnosis (B3) | all 13 early days | 13 |

**The measurement rests on two snapshots two hours apart.** The thirteen
earlier days produced the *diagnostics*, not the result.

That isn't wasted effort. Without them, the two that mattered would have been
uninterpretable — the ladder bug would have stayed invisible, and the forward
bias would have looked like a one-off glitch instead of a systematic offset
with a diagnosable signature.

---

# PART D — Glossary

| term | meaning |
|---|---|
| **spot (S)** | current stock price |
| **strike (K)** | the fixed price in the option contract |
| **expiry (T)** | when the option dies; also time remaining, in years |
| **call / put** | right to buy / right to sell |
| **OTM / ATM / ITM** | out of / at / in the money |
| **0DTE** | expiring today |
| **premium** | the option's price |
| **mid price** | (bid + ask) / 2 |
| **implied volatility (IV)** | the volatility that makes Black-Scholes match the market price |
| **vol point** | one percentage point of IV; 20% → 23% is "3 vol points" |
| **total variance** | `σ²T` — the additive measure of uncertainty |
| **forward variance** | variance the market assigns between two expiries |
| **forward (F)** | price for future delivery: `S·e^((r−q)T)` |
| **put-call parity** | `C − P = S·e^(−qT) − K·e^(−rT)`; model-free |
| **moneyness** | `ln(K/S)` — proportional distance from the money |
| **skew / smile** | IV varying by strike |
| **term structure** | IV varying by expiry |
| **IV crush** | the collapse in IV once an event resolves |
| **event premium** | extra variance priced into a window containing a known event |
| **calibration** | solving for the forward that makes put and call wings agree |
| **wing-averaging** | averaging put-side and call-side ATM IV to cancel the forward bias |
| **leverage (statistics)** | a distant data point dominating a regression |
| **standard deviation (1σ)** | the ±band containing ~68% of outcomes |
