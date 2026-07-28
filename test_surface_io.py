"""Regression tests for surface_io. Run with: python test_surface_io.py

No pytest dependency — plain asserts, so it runs anywhere the pipeline does.
Builds its own v2 fixture, so it works before any v2 snapshot is committed.
"""

import os
import shutil
import tempfile
from datetime import datetime

import numpy as np
import pandas as pd

from data import ET, time_to_expiry, r as RATE, q as DIVYIELD
from main import bs_price, bs_delta
from surface_io import load_all, load_snapshot, parse_filename, snapshot_timestamp

V1_FIXTURE = "data/surface_2026-07-27.csv"


def test_filename_parsing():
    assert parse_filename("data/surface_2026-07-29.csv") == ("2026-07-29", None)
    assert parse_filename("data/surface_2026-07-29_pre.csv") == ("2026-07-29", "pre")
    try:
        parse_filename("data/junk.csv")
    except ValueError:
        pass
    else:
        raise AssertionError("should reject an unrecognised filename")
    print("filename parsing              ok")


def test_dst_boundary():
    """snapshot_timestamp must round-trip without losing an hour across DST.

    Regression: parsing snapshot_ts with pd.to_datetime produced a pandas
    Timestamp whose arithmetic against a ZoneInfo-aware expiry silently
    dropped 3600s for expiries after DST ends.
    """
    ts = datetime(2026, 7, 28, 15, 0, tzinfo=ET)          # EDT
    parsed = snapshot_timestamp(pd.DataFrame({"snapshot_ts": [ts.isoformat()]}),
                                "2026-07-28")
    for expiry in ["2026-08-21", "2026-12-18", "2027-01-15", "2028-01-21"]:
        drift = abs(time_to_expiry(expiry, ts) - time_to_expiry(expiry, parsed))
        assert drift * 365 * 24 * 3600 < 1e-3, f"{expiry} drifts by {drift}"
    print("DST boundary                  pre/post-DST expiries agree to <1ms")


def test_v1_reconstruction():
    raw = pd.read_csv(V1_FIXTURE)
    S = raw["spot"].iloc[0]
    snap = datetime.strptime(raw["snapshot_date"].iloc[0], "%Y-%m-%d").date()
    raw["strike"] = S * np.exp(raw["log_moneyness"])
    raw["expiry"] = [(snap + pd.Timedelta(days=int(n))).strftime("%Y-%m-%d")
                     for n in (raw["T"] * 365).round()]

    d = load_snapshot(V1_FIXTURE)
    assert (d["schema"] == "v1").all()
    assert set(d["expiry"]) == set(raw["expiry"])
    assert ((d["log_moneyness"] < 0) == (d["option_type"] == "put")).all()
    assert ((d["delta"] < 0) == (d["option_type"] == "put")).all()
    assert d["delta"].abs().max() < 1
    print("v1 reconstruction             expiry/strike/type/delta exact")

    j = d.merge(raw[["expiry", "strike", "iv"]].rename(columns={"iv": "iv_old"}),
                on=["expiry", "strike"])
    assert len(j) == len(d), "merge changed row count"
    shift = (j["iv"] - j["iv_old"]) * 100

    # v1's whole-day T understates remaining life, so it overstates iv:
    # every corrected value must come DOWN, most at the front.
    assert (shift < 0).all(), "all v1 iv corrections must be negative"
    assert shift.abs().max() < 0.5, f"correction too large: {shift.abs().max()}"
    by_t = j.assign(s=shift).groupby(j["days_to_expiry"].round())["s"].mean().abs()
    assert by_t.iloc[0] == by_t.max(), "largest correction must be the front expiry"
    assert by_t[by_t.index > 30].max() < 0.02, "beyond a month should be negligible"
    print(f"v1 clock correction           {by_t.iloc[0]:.3f} pts at front, "
          f"<{by_t[by_t.index > 30].max():.3f} beyond 30d")


def _write_v2_fixture(dest, snapshot_date, hour=15):
    """Build a v2-schema snapshot from real v1 quotes."""
    src = pd.read_csv(V1_FIXTURE)
    S = src["spot"].iloc[0]
    ts = datetime.strptime(snapshot_date, "%Y-%m-%d").replace(hour=hour, tzinfo=ET)
    base = datetime.strptime(src["snapshot_date"].iloc[0], "%Y-%m-%d").date()

    strike = S * np.exp(src["log_moneyness"].values)
    cp = np.where(src["log_moneyness"].values < 0, "put", "call")
    expiry = np.array([(base + pd.Timedelta(days=int(n))).strftime("%Y-%m-%d")
                       for n in (src["T"] * 365).round()])
    T = np.array([time_to_expiry(e, ts) for e in expiry])

    keep = T > 0
    strike, cp, expiry, T = strike[keep], cp[keep], expiry[keep], T[keep]
    iv = src["iv"].values[keep]
    mid = np.array([bs_price(S, k, t, RATE, v, DIVYIELD, c)
                    for k, t, v, c in zip(strike, T, iv, cp)])
    delta = np.array([bs_delta(S, k, t, RATE, v, DIVYIELD, c)
                      for k, t, v, c in zip(strike, T, iv, cp)])

    pd.DataFrame(dict(
        expiry=expiry, T=T, strike=strike, log_moneyness=np.log(strike / S),
        option_type=cp, iv=iv, delta=delta, bid=mid - 0.01, ask=mid + 0.01,
        mid=mid, openInterest=100, spot=S, snapshot_date=snapshot_date,
        snapshot_ts=ts.isoformat(),
    )).to_csv(dest, index=False)


def test_v2_passthrough_and_mixed():
    tmp = tempfile.mkdtemp()
    try:
        os.makedirs(f"{tmp}/data")
        shutil.copy(V1_FIXTURE, f"{tmp}/data/")
        v2_path = f"{tmp}/data/surface_2026-07-28.csv"
        _write_v2_fixture(v2_path, "2026-07-28")

        raw2 = pd.read_csv(v2_path)
        d2 = load_snapshot(v2_path)
        assert (d2["schema"] == "v2").all()
        for col in ("iv", "mid", "delta", "T"):
            assert np.allclose(d2[col].values, raw2[col].values, atol=1e-12), \
                f"v2 {col} must pass through untouched"
        assert d2["bid"].notna().all() and d2["openInterest"].notna().all()
        print("v2 passthrough                iv/mid/delta/T bit-identical")

        n_v1 = len(load_snapshot(f"{tmp}/data/surface_2026-07-27.csv"))
        combined = load_all(f"{tmp}/data/surface_*.csv")
        assert combined["snapshot_ts"].nunique() == 2
        assert set(combined["schema"]) == {"v1", "v2"}
        assert combined["T"].gt(0).all() and combined["iv"].notna().all()
        assert combined["bid"].isna().sum() == n_v1, \
            "bid should be null exactly on v1 rows"
        assert combined["bid"].notna().sum() == len(d2)
        print(f"mixed load                    {len(combined)} rows, both eras, "
              "one schema")

        shutil.copy(V1_FIXTURE, f"{tmp}/data/surface_2026-07-26_dryrun.csv")
        assert load_all(f"{tmp}/data/surface_*.csv")["snapshot_ts"].nunique() == 2
        print("label exclusion               test runs filtered out")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_filename_parsing()
    test_dst_boundary()
    test_v1_reconstruction()
    test_v2_passthrough_and_mixed()
    print("\nAll surface_io tests passed.")
