import yfinance as yf
import pandas as pd
import numpy as np
from main import implied_vol, bs_delta
from datetime import datetime
from zoneinfo import ZoneInfo
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa
import os

TICKER = "SPY"
r = 0.045 #Risk-free Rate
q = 0.012 #SPY Dividend

ET = ZoneInfo("America/New_York")

# Expiries are chosen by TARGET DATE OFFSET, not by list index.
#
# The old selection was spy.options[:40:3] — every 3rd expiry by position. But
# as expiries roll off the front, the whole list shifts, so the stride lands on
# a different set of dates each day. Across 13 snapshots that produced 41
# distinct expiries with no single expiry present in more than 6 of them, which
# makes it impossible to track one expiry's IV through an event.
#
# Selecting the nearest available expiry to a fixed set of horizons gives a
# ladder that ages consistently day to day.
TARGET_OFFSET_DAYS = [1, 3, 7, 14, 30, 60, 90, 180, 365, 730]

# Expiries that must be captured every run regardless of the ladder, because
# they bracket the July 28-29 2026 FOMC meeting. Silently ignored if the
# exchange doesn't list them.
ALWAYS_INCLUDE = [
    "2026-07-28", "2026-07-29", "2026-07-30", "2026-07-31",
    "2026-08-04", "2026-08-07", "2026-08-21",
]


def time_to_expiry(expiry, now=None):
    """Year fraction from now to 4:00pm ET on the expiry date.

    Calendar-day resolution (the old (expiry - today).days / 365) is fine for
    anything a week out, but it breaks for 0DTE: an option expiring today gets
    T=0 and divides by zero in d1. On FOMC day the 0DTE contract is the most
    informative one on the board, so time-of-day resolution is needed.
    """
    if now is None:
        now = datetime.now(tz=ET)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    exp_dt = datetime.strptime(expiry, "%Y-%m-%d").replace(
        hour=16, minute=0, tzinfo=ET
    )
    return (exp_dt - now).total_seconds() / (365.0 * 24 * 3600)


def select_expiries(available, now=None,
                    targets=TARGET_OFFSET_DAYS, always=ALWAYS_INCLUDE):
    """Pick a date-anchored expiry ladder from the listed expiries.

    For each horizon in `targets`, take the closest available expiry; union
    that with any `always` dates the exchange actually lists.
    """
    if now is None:
        now = datetime.now(tz=ET)
    today = now.date()

    listed = set(available)
    chosen = {e for e in always if e in listed}

    future = [
        (e, (datetime.strptime(e, "%Y-%m-%d").date() - today).days)
        for e in available
    ]
    future = [(e, d) for e, d in future if d >= 0]

    for t in targets:
        if not future:
            break
        # tie-break toward the nearer expiry
        best, _ = min(future, key=lambda ed: (abs(ed[1] - t), ed[1]))
        chosen.add(best)

    return sorted(chosen)


def smile_for_expiry(spy, expiry, spot, now=None):
    """One expiry's smile. Returns (DataFrame, stats) — stats records how many
    quotes were dropped and why, so a data-quality regression is visible."""
    stats = {"expiry": expiry, "raw": 0, "filtered": 0, "iv_failed": 0, "kept": 0}

    T = time_to_expiry(expiry, now)
    if T <= 0:
        return None, stats

    chain = spy.option_chain(expiry)
    calls = chain.calls.copy()
    puts = chain.puts.copy()
    stats["raw"] = len(calls) + len(puts)

    calls["mid"] = (calls["bid"] + calls["ask"]) / 2
    puts["mid"] = (puts["bid"] + puts["ask"]) / 2
    otm_calls = calls[(calls["strike"] > spot) & (calls["bid"] > 0)
                  & ((calls["ask"] - calls["bid"]) / calls["mid"] < 0.5) & (calls["openInterest"] > 0)].copy()
    otm_puts = puts[(puts["strike"] < spot) & (puts["bid"] > 0)
                & ((puts["ask"] - puts["bid"]) / puts["mid"] < 0.5) & (puts["openInterest"] > 0)].copy()
    stats["filtered"] = stats["raw"] - (len(otm_calls) + len(otm_puts))

    otm_calls["option_type"] = "call"
    otm_puts["option_type"] = "put"

    def compute_iv(row, cp):
        try:
            return implied_vol(
                price = row["mid"],
                S = spot,
                K = row["strike"],
                T = T,
                r = r,
                q = q,
                cp = cp,
            )
        except Exception:
            # brentq raising "different signs" means the quote violates
            # arbitrage bounds and has no valid IV — a data-quality reject.
            return None

    otm_calls["iv"] = otm_calls.apply(lambda row: compute_iv(row, "call"), axis=1)
    otm_puts["iv"] = otm_puts.apply(lambda row: compute_iv(row, "put"), axis=1)

    before = len(otm_calls) + len(otm_puts)
    otm_calls = otm_calls[otm_calls["iv"].notna()]
    otm_puts = otm_puts[otm_puts["iv"].notna()]
    stats["iv_failed"] = before - (len(otm_calls) + len(otm_puts))

    cols = ["strike", "bid", "ask", "mid", "openInterest", "option_type", "iv"]
    smile = pd.concat([otm_puts[cols], otm_calls[cols]], ignore_index=True)
    if len(smile) == 0:
        return None, stats

    smile["delta"] = smile.apply(
        lambda row: bs_delta(spot, row["strike"], T, r, row["iv"], q,
                             row["option_type"]),
        axis=1,
    )
    smile["log_moneyness"] = np.log(smile["strike"] / spot)
    smile["T"] = T
    smile["expiry"] = expiry
    stats["kept"] = len(smile)

    return smile[["expiry", "T", "strike", "log_moneyness", "option_type",
                  "iv", "delta", "bid", "ask", "mid", "openInterest"]], stats


def build_surface(spy, spot, now=None, verbose=True):
    """Build the full surface DataFrame across the selected expiry ladder."""
    if now is None:
        now = datetime.now(tz=ET)

    expiries = select_expiries(spy.options, now=now)
    if verbose:
        print(f"Selected {len(expiries)} expiries: {', '.join(expiries)}")

    all_smiles = []
    all_stats = []
    for exp in expiries:
        try:
            result, stats = smile_for_expiry(spy, exp, spot, now=now)
        except Exception as e:
            print(f"  {exp}: FAILED ({e})")
            continue
        all_stats.append(stats)
        if result is not None and len(result) > 0:
            all_smiles.append(result)
        if verbose:
            print(f"  {exp}: kept {stats['kept']}/{stats['raw']} "
                  f"(filters {stats['filtered']}, no-IV {stats['iv_failed']})")

    if not all_smiles:
        raise RuntimeError("no usable option data for any selected expiry")

    surface = pd.concat(all_smiles, ignore_index=True)
    if verbose:
        failed = sum(s["iv_failed"] for s in all_stats)
        print(f"Total rows: {len(surface)}; quotes with no valid IV: {failed}")
    return surface


def save_daily_surface(surface, spot, label=None, now=None):
    """Save a surface snapshot to a dated CSV in data/.

    `label` suffixes the filename so multiple snapshots can be taken in one
    day without overwriting (e.g. label="pre" and label="post" around the
    FOMC announcement).
    """
    os.makedirs("data", exist_ok=True)
    if now is None:
        now = datetime.now(tz=ET)
    today = now.strftime("%Y-%m-%d")

    surface = surface.copy()
    surface["spot"] = spot
    surface["snapshot_date"] = today
    # full timestamp, so an off-schedule run is recorded in the data itself
    # rather than only in the notes
    surface["snapshot_ts"] = now.isoformat()

    suffix = f"_{label}" if label else ""
    path = f"data/surface_{today}{suffix}.csv"
    surface.to_csv(path, index=False)
    print(f"Saved {len(surface)} rows to {path}")
    return path

if __name__ == "__main__":
    # this only runs when you do `python data.py` directly
    spy = yf.Ticker(TICKER)
    hist = spy.history(period="1d")
    if hist.empty:
        raise RuntimeError("yfinance returned no price data for SPY — likely rate-limited, wait and retry")
    spot = hist["Close"].iloc[-1]

    surface = build_surface(spy, spot)
    os.makedirs("charts", exist_ok=True)
    surface.to_csv("charts/surface.csv", index=False)

    # ---- 3D surface plot ----
    fig = plt.figure(figsize=(12, 8))
    ax = fig.add_subplot(111, projection="3d")
    ax.scatter(surface["log_moneyness"], surface["T"], surface["iv"],
               c=surface["iv"], cmap="viridis", s=10)
    ax.set_xlabel("Log-moneyness ln(K/S)")
    ax.set_ylabel("Time to expiry (years)")
    ax.set_zlabel("Implied volatility")
    ax.set_title("SPY Implied Volatility Surface")
    plt.savefig("charts/surface.png", dpi=150, bbox_inches="tight")
    plt.show()
    plt.close()

    # ---- heatmap ----
    clipped = surface[(surface["log_moneyness"] > -0.3) & (surface["log_moneyness"] < 0.15)].copy()
    clipped["m_bin"] = pd.cut(clipped["log_moneyness"], bins=30)
    clipped["T_round"] = clipped["T"].round(3)

    grid = clipped.pivot_table(
        index="T_round", columns="m_bin", values="iv",
        aggfunc="mean", observed=False,
    )

    plt.figure(figsize=(12, 7))
    plt.imshow(grid.values, aspect="auto", origin="lower", cmap="viridis")
    plt.colorbar(label="Implied volatility")
    plt.xlabel("Log-moneyness bucket (low strike → high strike)")
    plt.ylabel("Time to expiry index (near → far)")
    plt.title("SPY Implied Volatility Surface — heatmap")
    plt.savefig("charts/heatmap.png", dpi=150, bbox_inches="tight")
    plt.show()
    plt.close()
