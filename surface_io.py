"""Loader that normalises every snapshot into one consistent schema.

Two schema eras exist in data/:

  v1 (2026-07-09 .. 2026-07-27)
      log_moneyness, T, iv, spot, snapshot_date
      T is WHOLE CALENDAR DAYS / 365.

  v2 (2026-07-28 onward)
      expiry, T, strike, log_moneyness, option_type, iv, delta,
      bid, ask, mid, openInterest, spot, snapshot_date, snapshot_ts
      T is a year fraction to 4:00pm ET.

Everything missing from v1 is recoverable except bid/ask/openInterest:

    expiry       = snapshot_date + round(T*365)      (exact; verified to 1e-13)
    strike       = spot * exp(log_moneyness)         (exact)
    option_type  = sign of log_moneyness             (exact — OTM-only filter)
    mid          = bs_price(S, K, T_v1, r, iv, q)    (exact — iv came from
                                                      inverting that mid)

The one substantive difference is T. v1 treats a 3:00pm snapshot as if the
option expired at midnight, so it understates the remaining life by an hour and
therefore OVERSTATES iv — by ~0.16 vol points at 3 days, ~0.05 at 8 days, and
essentially nothing beyond a month. Small, but the convention changes on
2026-07-28, one day before the FOMC event, which would put an artificial step
in the middle of the measurement. So v1 rows are re-inverted onto the v2 clock:
reconstruct the mid at the v1 T, then solve for iv again at the correct T.

Usage:
    from surface_io import load_all
    df = load_all()

    python surface_io.py          # summary of everything in data/
"""

import glob
import os
import re
from datetime import datetime

import numpy as np
import pandas as pd

from main import bs_price, bs_delta, implied_vol
from data import ET, time_to_expiry, r as RATE, q as DIVYIELD

# The daily job runs at 15:00 ET. v1 files record only a date, so the time has
# to be supplied here. notes.md documents one exception: on 2026-07-15 the
# 3:00pm run was missed (wifi outage) and the snapshot was taken at 3:45pm.
DEFAULT_SNAPSHOT_TIME = (15, 0)
KNOWN_SNAPSHOT_TIMES = {
    "2026-07-15": (15, 45),
}

OUT_COLS = [
    "snapshot_date", "snapshot_ts", "label", "schema",
    "expiry", "T", "days_to_expiry",
    "strike", "log_moneyness", "option_type",
    "mid", "iv", "delta",
    "bid", "ask", "openInterest", "spot",
]

_FNAME = re.compile(r"surface_(\d{4}-\d{2}-\d{2})(?:_([A-Za-z0-9]+))?\.csv$")


def parse_filename(path):
    """-> (date string, label or None). Raises on an unrecognised name."""
    m = _FNAME.search(os.path.basename(path))
    if not m:
        raise ValueError(f"unrecognised snapshot filename: {path}")
    return m.group(1), m.group(2)


def snapshot_timestamp(df, snapshot_date):
    """The moment the snapshot was taken, as a tz-aware datetime."""
    if "snapshot_ts" in df.columns and df["snapshot_ts"].notna().any():
        # datetime.fromisoformat, not pd.to_datetime: mixing a pandas Timestamp
        # with a ZoneInfo-aware datetime in `exp_dt - now` silently drops an
        # hour across the EST/EDT boundary (caught on the Dec/Jan expiries).
        ts = datetime.fromisoformat(str(df["snapshot_ts"].iloc[0]))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=ET)
        return ts.astimezone(ET)
    hh, mm = KNOWN_SNAPSHOT_TIMES.get(snapshot_date, DEFAULT_SNAPSHOT_TIME)
    return datetime.strptime(snapshot_date, "%Y-%m-%d").replace(
        hour=hh, minute=mm, tzinfo=ET
    )


def load_snapshot(path, rate=RATE, divyield=DIVYIELD):
    """Load one snapshot CSV and return it in the normalised schema."""
    raw = pd.read_csv(path)
    if len(raw) == 0:
        raise ValueError(f"{path} is empty")

    date_str, label = parse_filename(path)
    ts = snapshot_timestamp(raw, date_str)
    is_v2 = "expiry" in raw.columns

    d = pd.DataFrame(index=raw.index)
    d["snapshot_date"] = date_str
    d["snapshot_ts"] = ts.isoformat()
    d["label"] = label
    d["schema"] = "v2" if is_v2 else "v1"
    d["spot"] = raw["spot"].values

    if is_v2:
        d["expiry"] = raw["expiry"].values
        d["strike"] = raw["strike"].values
        d["option_type"] = raw["option_type"].values
        d["mid"] = raw["mid"].values
        d["iv"] = raw["iv"].values
        for c in ("bid", "ask", "openInterest"):
            d[c] = raw[c].values if c in raw.columns else np.nan
    else:
        # ---- reconstruct what v1 didn't store ----
        snap_day = datetime.strptime(date_str, "%Y-%m-%d").date()
        days = (raw["T"] * 365).round().astype(int)
        d["expiry"] = [
            (snap_day + pd.Timedelta(days=int(n))).strftime("%Y-%m-%d")
            for n in days
        ]
        d["strike"] = raw["spot"].values * np.exp(raw["log_moneyness"].values)
        # OTM-only filter guarantees this mapping
        d["option_type"] = np.where(
            raw["log_moneyness"].values < 0, "put", "call"
        )
        d["bid"] = np.nan
        d["ask"] = np.nan
        d["openInterest"] = np.nan

        # reconstruct the mid at the ORIGINAL clock, then re-solve iv on the
        # corrected one — see module docstring
        mids, ivs = [], []
        for K, T_old, iv_old, S, cp in zip(
            d["strike"], raw["T"], raw["iv"], raw["spot"], d["option_type"]
        ):
            px = bs_price(S, K, T_old, rate, iv_old, divyield, cp)
            mids.append(px)
            ivs.append(px)  # placeholder, replaced below
        d["mid"] = mids
        d["iv"] = np.nan  # filled after T is known

    # ---- one clock for every row ----
    # v2 already stores T computed at collection time by time_to_expiry, so
    # trust it; recomputing here would be redundant and is one more place for
    # a timezone discrepancy to creep in. Only v1 needs a clock correction.
    if is_v2:
        d["T"] = raw["T"].values
    else:
        d["T"] = [time_to_expiry(e, ts) for e in d["expiry"]]
    d["days_to_expiry"] = d["T"] * 365
    d["log_moneyness"] = np.log(d["strike"] / d["spot"])

    if not is_v2:
        ivs = []
        for px, S, K, T, cp in zip(
            d["mid"], d["spot"], d["strike"], d["T"], d["option_type"]
        ):
            try:
                ivs.append(implied_vol(px, S, K, T, rate, divyield, cp))
            except Exception:
                ivs.append(np.nan)
        d["iv"] = ivs

    if is_v2 and "delta" in raw.columns:
        d["delta"] = raw["delta"].values
    else:
        d["delta"] = [
            bs_delta(S, K, T, rate, iv, divyield, cp)
            if np.isfinite(iv) and T > 0 else np.nan
            for S, K, T, iv, cp in zip(
                d["spot"], d["strike"], d["T"], d["iv"], d["option_type"]
            )
        ]

    # drop expired/degenerate rows and any quote that lost its iv in the
    # re-inversion (an arbitrage violation under the corrected clock)
    d = d[(d["T"] > 0) & d["iv"].notna()]
    return d[OUT_COLS].reset_index(drop=True)


def load_all(pattern="data/surface_*.csv", exclude_labels=("afterhours", "dryrun",
                                                           "smoketest", "mocktest")):
    """Load every snapshot into one frame, sorted by time then expiry.

    Labelled test runs are excluded by default; `label` is preserved so the
    real pre/post pair on FOMC day stays distinguishable.
    """
    frames = []
    for path in sorted(glob.glob(pattern)):
        try:
            _, label = parse_filename(path)
        except ValueError:
            continue
        if label in exclude_labels:
            continue
        frames.append(load_snapshot(path))
    if not frames:
        raise RuntimeError(f"no snapshots matched {pattern}")
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values(["snapshot_ts", "expiry", "strike"]).reset_index(drop=True)


if __name__ == "__main__":
    df = load_all()
    print(f"{len(df)} rows from {df['snapshot_ts'].nunique()} snapshots\n")
    print("%-12s %-6s %-5s %6s %5s %7s %7s" % (
        "date", "label", "schema", "rows", "exps", "spot", "ATM~"))
    for ts, g in df.groupby("snapshot_ts"):
        near = g[np.isclose(g["T"], g["T"].min())]
        atm = np.nan
        if len(near) > 2:
            s = near.sort_values("log_moneyness")
            atm = np.interp(0.0, s["log_moneyness"], s["iv"]) * 100
        print("%-12s %-6s %-5s %6d %5d %7.2f %6.1f%%" % (
            g["snapshot_date"].iloc[0], g["label"].iloc[0] or "-",
            g["schema"].iloc[0], len(g), g["expiry"].nunique(),
            g["spot"].iloc[0], atm))
