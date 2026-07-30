"""FOMC event-premium analysis.

Run:  python analysis.py

Steps:
  1. Calibrate the forward per expiry, correcting the stale-spot bias
     (RESULTS.md section 4) instead of just wing-averaging around it.
  2. Build the ATM term structure per snapshot, in total-variance terms.
  3. Decompose the 1pm -> 3pm change on FOMC day into a one-off event chunk
     and an ongoing variance-rate shift.
  4. Build a null band from the pre-event snapshots, so the crush can be
     compared against normal day-to-day movement.
  5. Write charts to charts/.

Variance, not implied vol, is the working quantity: variance is additive in
time, so differences between expiries mean something and a parallel shift in
the surface cancels out of them.
"""

import os

import matplotlib
matplotlib.use("Agg")           # write files; never try to open a window
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import brentq

from main import bs_price, implied_vol
from surface_io import load_all
from data import r as RATE, q as DIVYIELD

EVENT_DATE = "2026-07-29"
FIXED_TENORS = [2, 5, 10, 20, 30, 60]      # days, for cross-snapshot comparison
ATM_WINDOW = 0.02                           # |log-moneyness| band treated as ATM


# ----------------------------------------------------------------- forward

def _wing_ivs(g, F, T):
    """Re-invert every quote against forward F; return (put_atm, call_atm).

    Working in the forward measure: undiscount the mid, then price with
    S=F, r=q=0. Whatever F is correct makes the two wings agree at K=F.
    """
    m = np.log(g["strike"].values / F)
    out = {}
    for side, mask in (("put", m < 0), ("call", m > 0)):
        sel = g[mask & (g["option_type"] == side).values]
        if len(sel) < 2:
            return None
        ms, ivs = [], []
        for row in sel.itertuples():
            try:
                iv = implied_vol(row.mid * np.exp(RATE * T), F, row.strike,
                                 T, 0.0, 0.0, row.option_type)
            except Exception:
                continue
            ms.append(np.log(row.strike / F))
            ivs.append(iv)
        if len(ms) < 2:
            return None
        order = np.argsort(ms)
        ms, ivs = np.asarray(ms)[order], np.asarray(ivs)[order]
        # nearest points to the money carry the signal; ignore far wings
        near = np.abs(ms) < ATM_WINDOW
        if near.sum() >= 2:
            ms, ivs = ms[near], ivs[near]
        out[side] = float(np.interp(0.0, ms, ivs))
    return out["put"], out["call"]


def calibrate_forward(g, T, spot, width=0.03):
    """Solve for the forward that makes the put and call wings agree.

    Returns (F, atm_iv, n_iter_ok) or (nan, nan, False) if it cannot be
    bracketed — some expiries simply lack strikes on both sides of the money.
    """
    # Only near-money quotes matter: the wings are interpolated to K=F, so
    # inverting deep-OTM strikes on every solver iteration is wasted work.
    # Keep a band comfortably wider than the search range for F.
    near = g[np.abs(np.log(g["strike"] / spot)) < width + ATM_WINDOW + 0.01]
    if len(near) < 4:
        return np.nan, np.nan, False
    g = near

    def gap(F):
        w = _wing_ivs(g, F, T)
        return np.nan if w is None else w[0] - w[1]

    lo, hi = spot * (1 - width), spot * (1 + width)
    g_lo, g_hi = gap(lo), gap(hi)
    if not (np.isfinite(g_lo) and np.isfinite(g_hi)) or g_lo * g_hi > 0:
        return np.nan, np.nan, False
    try:
        F = brentq(gap, lo, hi, xtol=1e-4)
    except Exception:
        return np.nan, np.nan, False
    w = _wing_ivs(g, F, T)
    if w is None:
        return np.nan, np.nan, False
    return F, 0.5 * (w[0] + w[1]), True


def wing_average_atm(g):
    """Fallback when calibration fails: average the wings.

    The bias is antisymmetric — it inflates puts and deflates calls by roughly
    equal amounts — so the mean cancels it to first order.
    """
    p = g[(g.log_moneyness < 0) & (g.log_moneyness > -ATM_WINDOW)].sort_values("log_moneyness")
    c = g[(g.log_moneyness > 0) & (g.log_moneyness < ATM_WINDOW)].sort_values("log_moneyness")
    if len(p) < 2 or len(c) < 2:
        return np.nan
    return 0.5 * (np.interp(0, p.log_moneyness, p.iv)
                  + np.interp(0, c.log_moneyness, c.iv))


# ------------------------------------------------------------ term structure

def atm_term_structure(df):
    """One row per (snapshot, expiry): calibrated forward, ATM iv, variance."""
    rows = []
    for ts, snap in df.groupby("snapshot_ts"):
        spot = snap["spot"].iloc[0]
        for expiry, g in snap.groupby("expiry"):
            T = g["T"].iloc[0]
            if T <= 0:
                continue
            F, atm, ok = calibrate_forward(g, T, spot)
            if not ok:
                F, atm = np.nan, wing_average_atm(g)
            if not np.isfinite(atm):
                continue
            rows.append(dict(
                snapshot_ts=ts, snapshot_date=snap["snapshot_date"].iloc[0],
                label=snap["label"].iloc[0], expiry=expiry, T=T,
                days=T * 365, spot=spot, forward=F, calibrated=ok,
                atm_iv=atm, total_var=atm ** 2 * T,
            ))
    return pd.DataFrame(rows).sort_values(["snapshot_ts", "T"]).reset_index(drop=True)


def fixed_tenor_curve(ts, tenors=FIXED_TENORS):
    """Interpolate each snapshot's ATM curve onto fixed maturities.

    Necessary because the pre-07-27 snapshots used a rotating expiry ladder,
    so the same expiry is rarely present two days running. Fixed tenors are
    comparable across every snapshot regardless of which expiries were listed.
    """
    out = []
    for tsx, g in ts.groupby("snapshot_ts"):
        g = g.sort_values("days")
        if len(g) < 3:
            continue
        row = {"snapshot_ts": tsx, "snapshot_date": g["snapshot_date"].iloc[0],
               "label": g["label"].iloc[0]}
        for d in tenors:
            row[d] = (np.interp(d, g["days"], g["atm_iv"])
                      if g["days"].min() <= d <= g["days"].max() else np.nan)
        out.append(row)
    return pd.DataFrame(out)


# --------------------------------------------------------------- event maths

def decompose(pre, post):
    """Split the pre->post variance change into event chunk + rate shift.

        dV(T) = a + b*T

    `a` is a one-off release (the announcement); `b` is a change in the
    ongoing variance rate (a market-wide move). Reported with the front-only
    estimate too, because `a` is sensitive to leverage from long expiries.
    """
    m = pre.merge(post, on="expiry", suffixes=("_pre", "_post"))
    m["dV"] = m.total_var_pre - m.total_var_post

    def _fit(sub):
        A = np.vstack([np.ones(len(sub)), sub.T_pre]).T
        (a, b), *_ = np.linalg.lstsq(A, sub.dV, rcond=None)
        f = A @ np.array([a, b])
        r2 = 1 - ((sub.dV - f) ** 2).sum() / ((sub.dV - sub.dV.mean()) ** 2).sum()
        return a, b, r2

    a, b, r2 = _fit(m)
    # The long expiries have enormous leverage on the intercept — a single
    # 2-year point can move `a` by 20%+ — so refit on the maturities where the
    # event actually dominates and report both.
    sub = m[m.T_pre * 365 <= 60]
    a_s, b_s, r2_s = _fit(sub) if len(sub) >= 3 else (np.nan,) * 3

    A = np.vstack([np.ones(len(m)), m.T_pre]).T
    m["dV_fit"] = A @ np.array([a, b])
    m["dV_fit_short"] = A @ np.array([a_s, b_s]) if np.isfinite(a_s) else np.nan
    return m.sort_values("T_pre"), (a, b, r2), (a_s, b_s, r2_s)


def null_band(curve, event_date=EVENT_DATE):
    """Typical day-over-day move in ATM iv at each fixed tenor, pre-event.

    Gives the crush something to be compared against. Note it is a 24-hour
    benchmark being used against a 2-hour move, which makes it conservative.
    """
    pre = curve[(curve.snapshot_date < event_date) & curve.label.isna()]
    pre = pre.sort_values("snapshot_date")
    stats = {}
    for d in FIXED_TENORS:
        ch = pre[d].diff().dropna() * 100
        if len(ch) >= 3:
            stats[d] = dict(n=len(ch), sd=ch.std(),
                            p95=np.percentile(np.abs(ch), 95),
                            worst=np.abs(ch).max())
    return pd.DataFrame(stats).T


# ------------------------------------------------------------------- charts

def make_charts(ts, curve, decomp, outdir="charts"):
    os.makedirs(outdir, exist_ok=True)

    # 1. ATM term structure, one line per snapshot
    fig, ax = plt.subplots(figsize=(11, 6))
    snaps = sorted(ts.snapshot_ts.unique())
    cmap = plt.cm.viridis(np.linspace(0, 1, len(snaps)))
    for c, tsx in zip(cmap, snaps):
        g = ts[ts.snapshot_ts == tsx].sort_values("days")
        lbl = g.snapshot_date.iloc[0] + (f" {g.label.iloc[0]}" if pd.notna(g.label.iloc[0]) else "")
        is_event = g.snapshot_date.iloc[0] == EVENT_DATE
        ax.plot(g.days, g.atm_iv * 100, marker="o", ms=3, color=c,
                lw=2.4 if is_event else 1.0, alpha=1.0 if is_event else 0.55,
                label=lbl if is_event or tsx == snaps[0] else None)
    ax.set_xscale("log")
    ax.set_xlabel("days to expiry (log scale)")
    ax.set_ylabel("ATM implied volatility (%)")
    ax.set_title("SPY ATM term structure — dark = FOMC day, light = earlier snapshots")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.savefig(f"{outdir}/term_structure.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # 2. the crush: pre vs post, and the change by maturity
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 5))
    pre = ts[(ts.snapshot_date == EVENT_DATE) & (ts.label == "pre")].sort_values("days")
    post = ts[(ts.snapshot_date == EVENT_DATE) & ts.label.isna()].sort_values("days")
    a1.plot(pre.days, pre.atm_iv * 100, "o-", label="1pm (pre-announcement)")
    a1.plot(post.days, post.atm_iv * 100, "s-", label="3pm (post-announcement)")
    a1.set_xscale("log"); a1.set_xlabel("days to expiry"); a1.set_ylabel("ATM IV (%)")
    a1.set_title("FOMC day: before vs after 2:00pm"); a1.legend(); a1.grid(alpha=0.3)

    a2.plot(decomp.T_pre * 365, decomp.dV, "o", label="observed")
    a2.plot(decomp.T_pre * 365, decomp.dV_fit, "-", alpha=0.5,
            label="fit, all expiries (long-end leverage)")
    if decomp.dV_fit_short.notna().any():
        a2.plot(decomp.T_pre * 365, decomp.dV_fit_short, "--",
                label="fit, <=60d (preferred)")
    a2.set_yscale("log")
    a2.set_xscale("log"); a2.set_xlabel("days to expiry")
    a2.set_ylabel("variance released (pre − post)")
    a2.set_title("Variance decomposition"); a2.legend(); a2.grid(alpha=0.3)
    fig.savefig(f"{outdir}/crush.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # 3. front-end ATM iv through time, with the event marked
    fig, ax = plt.subplots(figsize=(11, 5))
    c = curve.copy()
    c["x"] = range(len(c))
    for d in (2, 10, 30):
        if d in c:
            ax.plot(c.x, c[d] * 100, marker="o", ms=4, label=f"{d}-day tenor")
    ev = c[c.snapshot_date == EVENT_DATE]
    for _, row in ev.iterrows():
        ax.axvline(row.x, color="crimson", ls="--", alpha=0.7)
    ax.set_xticks(c.x)
    ax.set_xticklabels([f"{r.snapshot_date[5:]}{'' if pd.isna(r.label) else ' ' + r.label}"
                        for r in c.itertuples()], rotation=60, ha="right", fontsize=8)
    ax.set_ylabel("ATM IV (%)")
    ax.set_title("ATM volatility at fixed tenors — dashed red = FOMC day snapshots")
    ax.legend(); ax.grid(alpha=0.3)
    fig.savefig(f"{outdir}/fixed_tenor.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


# --------------------------------------------------------------------- main

if __name__ == "__main__":
    df = load_all()
    print(f"loaded {len(df)} rows / {df.snapshot_ts.nunique()} snapshots\n")

    ts = atm_term_structure(df)
    ok = ts.calibrated.sum()
    print(f"forward calibration: {ok}/{len(ts)} expiries solved "
          f"({100*ok/len(ts):.0f}%); rest fall back to wing-averaging\n")

    cal = ts[ts.calibrated].copy()
    if len(cal):
        # Compare against the theoretical forward S*e^((r-q)T), not raw spot:
        # a long-dated forward legitimately sits above spot because of carry,
        # so measuring against spot would confuse carry with staleness.
        cal["f_theo"] = cal.spot * np.exp((RATE - DIVYIELD) * cal["T"])
        cal["stale"] = (cal.forward / cal.f_theo - 1) * 100
        print("calibrated forward vs THEORETICAL forward S*e^((r-q)T):")
        for lo, hi, lbl in [(0, 7, "  <1w "), (7, 60, "  1w-2m"), (60, 1e9, "  >2m ")]:
            s = cal[(cal.days >= lo) & (cal.days < hi)]["stale"]
            if len(s):
                print(f"{lbl}  n={len(s):3d}  median {s.median():+.3f}%  "
                      f"IQR [{s.quantile(.25):+.3f}%, {s.quantile(.75):+.3f}%]")
        print("(negative = quoted spot ran above what the option quotes imply)\n")

    pre = ts[(ts.snapshot_date == EVENT_DATE) & (ts.label == "pre")]
    post = ts[(ts.snapshot_date == EVENT_DATE) & ts.label.isna()]
    if len(pre) and len(post):
        print("=== FOMC day: 1pm -> 3pm ===")
        print("%-12s %7s %9s %9s %8s" % ("expiry", "days", "ATM pre", "ATM post", "change"))
        m = pre.merge(post, on="expiry", suffixes=("_pre", "_post")).sort_values("T_pre")
        for r in m.itertuples():
            print("%-12s %7.1f %8.1f%% %8.1f%% %+7.1f"
                  % (r.expiry, r.days_pre, r.atm_iv_pre * 100, r.atm_iv_post * 100,
                     (r.atm_iv_post - r.atm_iv_pre) * 100))

        d, full, short = decompose(pre, post)
        a, b, r2 = full
        a_s, b_s, r2_s = short
        print("\ndV(T) = a + b*T   (a = one-off event chunk, b = ongoing rate shift)")
        print(f"  all expiries    a = {a:.3e} -> {np.sqrt(max(a,0))*100:.2f}%   "
              f"b = {b:+.5f}   R2 = {r2:.3f}")
        if np.isfinite(a_s):
            print(f"  <=60d only      a = {a_s:.3e} -> {np.sqrt(max(a_s,0))*100:.2f}%   "
                  f"b = {b_s:+.5f}   R2 = {r2_s:.3f}")
        print("  (long expiries carry heavy leverage on the intercept; the")
        print("   short-dated fit and the direct reads below are more reliable)")
        front = d[d.days_pre < 15]
        if len(front):
            print(f"  front-only (<15d) mean dV = {front.dV.mean():.3e} "
                  f"-> implied move {np.sqrt(front.dV.mean())*100:.2f}%")
        z = d[d.days_pre < 0.5]
        if len(z):
            print(f"  0DTE direct read          = {z.dV.iloc[0]:.3e} "
                  f"-> implied move {np.sqrt(max(z.dV.iloc[0],0))*100:.2f}%")

        curve = fixed_tenor_curve(ts)
        nb = null_band(curve)
        if len(nb):
            print("\n=== null band: normal day-over-day ATM moves before the event ===")
            print("%8s %5s %8s %8s %8s %10s" % ("tenor", "n", "sd", "p95", "worst", "crush"))
            pre_c = curve[(curve.snapshot_date == EVENT_DATE) & (curve.label == "pre")]
            post_c = curve[(curve.snapshot_date == EVENT_DATE) & curve.label.isna()]
            for d_ in nb.index:
                crush = np.nan
                if len(pre_c) and len(post_c):
                    crush = (post_c[d_].iloc[0] - pre_c[d_].iloc[0]) * 100
                ratio = f"{abs(crush)/nb.loc[d_,'sd']:.1f}x sd" if np.isfinite(crush) else ""
                print("%7.0fd %5.0f %8.2f %8.2f %8.2f %9.2f  %s"
                      % (d_, nb.loc[d_, "n"], nb.loc[d_, "sd"], nb.loc[d_, "p95"],
                         nb.loc[d_, "worst"], crush, ratio))

        make_charts(ts, curve, d)
        print("\ncharts written to charts/: term_structure.png, crush.png, fixed_tenor.png")
