# Explainer — the vocabulary and the math, from scratch

Written for someone with no options background. Every number here is from this
project's actual data, and every calculation is shown.

`METHODOLOGY.md` = why the design is what it is.
`RESULTS.md` = what happened.
**This file = what the words and the math mean.**

---

## 1. The basic objects

An **option** is a contract giving the right — not the obligation — to trade a
stock at a fixed price on a fixed date.

- **Call option** — the right to *buy* at the fixed price. Valuable if the stock
  goes up.
- **Put option** — the right to *sell* at the fixed price. Valuable if the stock
  goes down.
- **Strike (K)** — the fixed price in the contract.
- **Expiry (T)** — the date the contract dies. SPY options expire at 4:00pm ET.
- **Spot (S)** — the stock's current price.
- **Premium** — what the option costs.

**SPY** is an ETF tracking the S&P 500. When SPY trades at 735, that's $735 per
share, and options on it have strikes like 730, 735, 740.

Vocabulary for where a strike sits relative to spot:

| term | meaning | example (spot = 735) |
|---|---|---|
| **at-the-money (ATM)** | strike ≈ spot | 735 strike |
| **out-of-the-money (OTM)** | worthless if exercised now | 750 call, 720 put |
| **in-the-money (ITM)** | has value if exercised now | 720 call, 750 put |

**0DTE** = "zero days to expiry" — an option expiring today.

This project only uses OTM options. ITM options are mostly just their
guaranteed value (a 720 call with spot at 735 is worth at least $15 no matter
what), so their prices carry very little information about uncertainty. OTM
options are *pure* uncertainty — they're worth something only if the stock
moves.

---

## 2. Why convert price into "implied volatility"

Say a 740 call costs $2.10. That number is nearly useless on its own. Is $2.10
expensive? It depends on the strike, how long until expiry, and where the stock
is. You can't compare $2.10 on a 3-day option to $2.10 on a 6-month option.

**Volatility** is how much a stock tends to move, quoted as an annualised
percentage. "20% volatility" means: over one year, one standard deviation of
movement is 20%.

The **Black-Scholes formula** takes six inputs and outputs a fair price:

```
(spot, strike, time, interest rate, dividend yield, volatility) -> price
```

Five of those six are known. Only volatility isn't. So you can run the formula
**backwards**: given the market's price, find the volatility that reproduces it.
That number is the **implied volatility (IV)** — the market's forecast of future
movement, backed out of what people are actually paying.

**Why "implied":** it isn't measured from history. It's *implied by* the price
people are willing to pay right now. It's a forecast, not a measurement.

### Running it backwards requires a root-find

Black-Scholes can't be rearranged to solve for volatility — the volatility
appears inside a cumulative normal distribution, which has no closed-form
inverse. So the solver guesses and narrows:

> "5% volatility gives a price of $0.40, too low. 60% gives $4.20, too high.
> Try 30%… $2.05, slightly low. Try 32%…"

That's **Brent's method** — a systematic version of that narrowing, guaranteed
to converge. `implied_vol` in `main.py` searches between 0.0001% and 500%.

**When it fails, that's information.** If *no* volatility in that whole range
reproduces the price, the quoted price is impossible — it violates a basic
no-arbitrage bound. So the solver's failures double as a bad-data filter.

---

## 3. Reading "the 737 put implied 33.3%"

The full sentence: *"On July 28 at 10:04am, SPY was at 737.40. A put option with
strike 737 expiring at 4:00pm that same day was quoted at a mid price of $2.355.
Feeding that price into Black-Scholes backwards gives 33.3% annualised
volatility."*

- **737** — the strike
- **put** — right to sell
- **implied** — backed out of the price, not measured from history
- **33.3%** — annualised volatility

**Important:** the option had only ~6 hours to live, but the 33.3% is still
quoted *per year*. That's the convention — always annualised, so options of
different maturities are comparable. Section 4 converts it back to a real
6-hour move.

---

## 4. Turning volatility into an expected move — the √T rule

Volatility is annualised, so to get the expected move over a shorter period you
scale it down. The scaling is by the **square root** of time, not time itself:

```
expected move over period T  =  sigma * sqrt(T)
```

**Why square root?** Stock moves are treated as roughly independent from one
period to the next. When you add independent random quantities, their
**variances** add — not their standard deviations. Volatility is a standard
deviation, so it grows with √time.

Concretely: if a day's move is ±1%, four days isn't ±4%. It's ±1% × √4 = **±2%**.
Some days go up, some down, and they partly cancel.

### The actual calculation behind "±1.07%"

At 1:00pm on July 29, the option expiring at 4:00pm that day had ATM implied
volatility of **58.0%**.

```
T = 3 hours = 3 / 8760 hours per year = 0.00034247 years
sqrt(T) = 0.018506
move = 0.580 * 0.018506 = 0.010733 = 1.07%
```

With SPY at 734.93, that's **±7.88 points**.

**What "±1.07%" actually claims:** it is one **standard deviation** — roughly a
68% chance the close lands within ±1.07%, and 32% chance outside. It is *not* a
maximum or a guarantee. It's the market's collective bet on the size of the
move, sign unknown.

**The outcome:** SPY closed the 1pm→3pm window at 742.02, a **+0.964%** move.
Inside the predicted band, with an hour still to go. The forecast was good.

---

## 5. Variance, and why it's the quantity that actually works

**Variance = volatility squared × time.** Written `V = sigma^2 * T`. This is
"total variance to expiry."

This is the central tool in the whole project, for one reason:

> **Variance adds up over time. Volatility does not.**

You cannot subtract a 3-day volatility from an 8-day volatility and get "the
volatility of the 5 days in between" — that's meaningless. But you *can*
subtract total variances, and the result is exactly the variance the market
assigns to the days in between:

```
variance of the window between two expiries  =  V(T2) - V(T1)
```

This is called **forward variance**, and it's what lets you isolate a *single
day*. Instead of vaguely noting "the front end looks high," you can say "the
market prices *this specific window* at N times an ordinary one."

Converting back to a move is just the square root:

```
implied move over a window = sqrt(variance of that window)
```

Check that this is consistent: for the 0DTE at 1pm,
`V = 0.580² × 0.00034247 = 0.00011521`, and `√0.00011521 = 1.07%`. Same answer
as Section 4 — because √(σ²T) is just σ√T.

---

## 6. "The market prices these 3 hours at 3.1× an ordinary 3-hour window"

Two numbers compared.

**Numerator — the event window.** The option expiring at 4pm on July 29,
measured at 1pm, contains the 2:00pm announcement:

```
V_event = 0.580^2 * (3/8760) = 0.00011521
```

**Denominator — an ordinary 3 hours.** Taken from the July 28 snapshot, using
two expiries far enough out that the announcement barely affects them:

```
V(Aug 21) - V(Aug 14) = 0.001492 - 0.001093 = 0.000399   over 5 trading days
normal daily variance = 0.000399 / 5 = 0.0000798
normal daily move     = sqrt(0.0000798) = 0.8933%
```

Scale one day (6.5 trading hours) down to 3 hours, using √T again:

```
normal 3h move = 0.8933% * sqrt(3/6.5) = 0.6069%
normal 3h variance = 0.006069^2 = 0.00003683
```

**The ratio:**

```
0.00011521 / 0.00003683 = 3.13x
```

**In plain terms:** three ordinary afternoon hours are worth about ±0.61% of
movement. These particular three hours were priced at ±1.07%. In variance terms
that's **3.1× as much risk packed into the same clock time** — and the only
thing different about them was the Fed.

**Stripping out the ordinary part** to isolate the announcement itself:

```
excess variance = 0.00011521 - 0.00003683 = 0.00007837
excess move     = sqrt(0.00007837) = 0.89%
```

That was the forecast: *the announcement itself is worth about ±0.89%.*

---

## 7. The forward, and why it isn't the spot price

The **forward price (F)** is the price for delivery of the stock at a future
date rather than today. It differs from spot for two reasons:

- **Interest** — paying later instead of now lets you earn interest meanwhile,
  which pushes the forward *up*.
- **Dividends** — a forward holder doesn't receive dividends paid in the
  meantime, which pushes the forward *down*.

```
F = S * e^((r - q) * T)
```

with `r` = interest rate (4.5% here) and `q` = dividend yield (1.2%).

Over 3 hours this is a rounding error. Over two years it's several percent. **The
forward, not spot, is the correct centre of the options market** — it's the
price both sides implicitly trade against.

---

## 8. Put-call parity — the rule that caught the bug

For the same strike and expiry, a call and a put are rigidly linked:

```
C - P = S*e^(-qT) - K*e^(-rT)
```

**Why this must hold.** Buy a call and sell a put, both at strike K. At expiry:

- Stock above K → you exercise the call, buy at K.
- Stock below K → the put you sold is exercised against you, you buy at K.

Either way you buy the stock at K. That combination is identical to a forward
contract, so it must cost the same. If it didn't, you could buy the cheap one,
sell the expensive one, and pocket a risk-free profit.

**This is not a model.** Black-Scholes could be completely wrong and parity
would still hold. It follows from the payoffs alone. That's what makes it a
reliable auditing tool.

### How it exposed the stale spot

On July 28 at 10:04am: spot 737.40, the 737 put quoted at $2.355, the 738 call
at $1.295, `T = 0.00068` years.

Parity gives what a 737 *call* must cost:

```
C(737) = 2.355 + 737.40*e^(-0.012*0.00068) - 737*e^(-0.045*0.00068)
       = 2.355 + 737.3940 - 736.9774
       = 2.7715
```

Now compare to the observed 738 call at $1.295:

```
C(737) - C(738) = 2.7715 - 1.295 = 1.4765
```

**That is impossible.** Buy the 737 call, sell the 738 call. At expiry that
position pays at most **$1.00** — the gap between the strikes. Above 738 both
options are exercised and the payoffs offset; below 737 both expire worthless.
So the position can never be worth more than $1.00, and it costs $1.4765.

Anyone could sell it and keep at least $0.47 risk-free.

**Real markets don't leave that lying around**, so the conclusion isn't "free
money." It's **"my inputs are inconsistent."** Specifically, the spot price came
from one data feed and the option quotes from another, timestamped differently.
Solving for the forward that makes both wings agree gives **≈736.35** — the spot
was running about **1 point stale**.

### Why this makes puts look expensive and calls look cheap

If the spot you plug in is too high, every put looks further out-of-the-money
than it really is. To justify its observed price, the solver has to assume more
volatility — so **put IVs come out inflated**. Calls are the mirror image: they
look closer to the money, so **call IVs come out deflated**.

That's exactly the pattern seen: puts high, calls low, at every expiry.

### Why the effect shrinks with maturity

A 1-point error on 735 is a 0.14% error in where the centre is. For a 3-day
option, whose whole distribution is about 2% wide, that's a big fraction. For a
338-day option, whose distribution is ~19% wide, it's negligible.

Measured on July 27:

| expiry | days | put ATM | call ATM | gap |
|---|---|---|---|---|
| 2026-07-30 | 3 | 22.4% | 17.0% | **+5.4** |
| 2026-08-04 | 8 | 18.0% | 14.8% | +3.2 |
| 2026-08-28 | 32 | 16.4% | 15.1% | +1.3 |
| 2027-06-30 | 338 | 19.2% | 18.9% | **+0.2** |

**That decay is the fingerprint.** A genuine market feature wouldn't fade with
maturity like that. It's what confirmed the diagnosis rather than leaving it a
guess.

### Two ways to deal with it

**Wing-averaging (quick).** The error pushes puts up and calls down by roughly
equal amounts — it's *antisymmetric*. So averaging the two cancels most of it:

```
ATM estimate = (put ATM + call ATM) / 2
```

For the July 30 expiry: (22.4 + 17.0)/2 = **19.7%**.

**Forward calibration (proper).** Search for the value of F that makes the two
wings agree exactly, then re-price everything against it. This is what
`analysis.py` does; it solved 135 of 175 expiries.

---

## 9. The crush, and why it fades with maturity

An event is a **fixed chunk of variance** — call it Δ — sitting inside every
expiry that spans it. Once the announcement happens, Δ is released.

Total variance is `V = σ²T`, so `σ = √(V/T)`. Removing Δ drops the volatility by
approximately:

```
drop in sigma  ~  delta / (2 * sigma * T)
```

**The `T` in the denominator is the whole story.** The same fixed chunk of
variance is a large fraction of a short option's total and a trivial fraction of
a long one's. Using Δ = 1.10 × 10⁻⁴ (the fitted event chunk):

| expiry | T (years) | σ | predicted event drop | **observed drop** |
|---|---|---|---|---|
| 2026-07-30 | 0.0029 | 28.9% | 6.67 pts | **6.8** |
| 2026-07-31 | 0.0058 | 25.3% | 3.73 pts | **5.6** |
| 2026-08-21 | 0.0631 | 16.8% | 0.52 pts | **2.4** |
| 2028-06-16 | 1.8850 | 21.0% | **0.01 pts** | **0.3** |

Two things to read here.

**First, the front matches almost exactly** — 6.67 predicted against 6.8
observed. The fixed-chunk model works where the event dominates.

**Second, the 2028 expiry is the key control.** The event should have moved it
by **0.01 vol points** — utterly invisible. It moved 0.3. So that 0.3 is *not*
the Fed. It's the market-wide volatility decline happening at the same time.

This is the heart of the identification. A market-wide move would push *all*
expiries down by similar amounts. An event pushes the front down enormously and
the back not at all. **The observed pattern — 6.8 at the front, 0.3 at the back
— can only be an event.**

---

## 10. Splitting the two effects apart

The middle expiries show more drop than the event alone explains (07-31:
observed 5.6, event-only 3.73). Both things happened at once. To separate them,
fit in variance space:

```
dV(T)  =  a  +  b*T
```

- **`a`** — a constant: variance released regardless of maturity. **The event.**
- **`b*T`** — grows with maturity: a change in the ongoing *rate* of variance
  per unit time. **The market-wide shift.**

Fitted results:

```
all expiries    a = 3.02e-4  ->  1.74%     b = +0.00119    R2 = 0.912
<=60 days only  a = 1.10e-4  ->  1.05%     b = +0.00504    R2 = 0.961
```

**Why two fits.** Least squares minimises squared error, so a point far from the
others dominates the answer. The 688-day expiry has variance ~50× larger than
the front expiries, so it dictates the line — and moves the estimated event size
from 1.05% to 1.74% by itself. That's called **leverage**, and it means the
all-expiry number can't be trusted. The short-dated fit is the honest one.

**An earlier attempt got this wrong.** Fitting `dIV = a/T + b` in *volatility*
space gave **R² = 0.02** — essentially no fit at all. The error was working in
the wrong units: volatility doesn't add up over time, variance does. Moving to
variance space took R² from 0.02 to 0.96. Same data, right coordinates.

**Honest caveat:** `a + b*T` is still a simplification. It assumes the
market-wide shift is a constant rate change at every maturity, but the 2028
expiry moved only 0.3 points while 08-21 moved 2.4. Real volatility shocks decay
with maturity because volatility mean-reverts. The two-component model captures
the main structure, not everything.

---

## 11. The null band — "is this bigger than a normal day?"

A number moving isn't evidence unless you know how much it normally moves. The
13 pre-event snapshots supply that baseline.

For each, the ATM volatility is interpolated to fixed maturities (10 days, 20
days…), then day-to-day changes are measured. Their **standard deviation** is
the typical daily wobble.

```
 tenor    n     sd    p95   worst   crush   ratio
   10d   13   2.06   3.83   4.04   -2.71   1.3x sd
   20d   13   1.49   2.86   3.03   -2.45   1.6x sd
   30d   13   1.09   1.95   2.28   -1.82   1.7x sd
   60d   13   0.84   1.55   1.79   -1.25   1.5x sd
```

**This is weak, and it should be reported as weak.** A 1.3–1.7× move is
unremarkable — normal days routinely produce that.

**And it's missing where it matters.** The crush was at 1–2 days (−6.8, −5.6
points), but the pre-event ladder almost never listed an expiry shorter than 3
days. So there's no baseline at the front — precisely where the effect lives.

That gap traces directly back to the expiry-sampling bug: it was fixed in time
to capture the event, but too late to have built a baseline at short maturities.

**So the real evidence isn't this test.** It's the pre-registered forecast
verifying out-of-sample, and the localization pattern in Section 9.

---

## 12. Glossary

| term | meaning |
|---|---|
| **spot (S)** | current stock price |
| **strike (K)** | the fixed price written into the option |
| **expiry (T)** | when the option dies; also the time remaining, in years |
| **call / put** | right to buy / right to sell |
| **OTM / ATM / ITM** | out of / at / in the money |
| **0DTE** | expiring today |
| **premium** | the option's price |
| **mid price** | (bid + ask) / 2 — the middle of the quote |
| **implied volatility (IV)** | the volatility that makes Black-Scholes match the market price |
| **vol point** | one percentage point of IV; 20% → 23% is "3 vol points" |
| **total variance** | `σ²T` — the additive measure of uncertainty |
| **forward variance** | variance the market assigns to the window between two expiries |
| **forward (F)** | price for future delivery: `S·e^((r−q)T)` |
| **put-call parity** | `C − P = S·e^(−qT) − K·e^(−rT)`; model-free |
| **moneyness** | `ln(K/S)` — distance from the money, in proportional terms |
| **skew / smile** | the pattern of IV varying by strike |
| **term structure** | the pattern of IV varying by expiry |
| **IV crush** | the collapse in IV after an event resolves |
| **event premium** | extra variance priced into a window containing a known event |
| **leverage (statistics)** | a distant data point dominating a regression |
| **standard deviation (1σ)** | the ±band containing ~68% of outcomes |
