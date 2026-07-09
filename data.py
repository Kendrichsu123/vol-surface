import yfinance as yf
import pandas as pd
import numpy as np
from main import implied_vol
from datetime import datetime
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa
import os

TICKER = "SPY"
r = 0.045 #Risk-free Rate
q = 0.012 #SPY Dividend

def smile_for_expiry(spy, expiry, spot):
    chain = spy.option_chain(expiry)
    calls = chain.calls
    puts = chain.puts

    calls["mid"] = (calls["bid"] + calls["ask"]) / 2
    puts["mid"] = (puts["bid"] + puts["ask"]) / 2
    otm_calls = calls[(calls["strike"] > spot) & (calls["bid"] > 0) 
                  & ((calls["ask"] - calls["bid"]) / calls["mid"] < 0.5) & (calls["openInterest"] > 0)].copy()
    otm_puts = puts[(puts["strike"] < spot) & (puts["bid"] > 0) 
                & ((puts["ask"] - puts["bid"]) / puts["mid"] < 0.5) & (puts["openInterest"] > 0)].copy()
    
    expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
    today = datetime.now().date()
    T = (expiry_date - today).days / 365
    if T <= 0:
        return None

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
            return None
        
    otm_calls["iv"] = otm_calls.apply(lambda row: compute_iv(row, "call"), axis=1)
    otm_puts["iv"] = otm_puts.apply(lambda row: compute_iv(row, "put"), axis=1)

    otm_calls = otm_calls[otm_calls["iv"].notna()]
    otm_puts = otm_puts[otm_puts["iv"].notna()]


    put_wing = otm_puts[["strike", "iv"]]
    call_wing = otm_calls[["strike", "iv"]]
    smile = pd.concat([put_wing, call_wing])
    smile["log_moneyness"] = np.log(smile["strike"] / spot)
    smile["T"] = T
    return smile[["log_moneyness", "T", "iv"]]


def build_surface(spy, spot):
    """Build the full surface DataFrame across sampled expiries."""
    all_smiles = []
    for exp in spy.options[:40:3]:
        result = smile_for_expiry(spy, exp, spot)
        if result is not None and len(result) > 0:
            all_smiles.append(result)
    return pd.concat(all_smiles, ignore_index=True)


def save_daily_surface(surface, spot):
    """Save today's surface to a dated CSV in a data/ folder."""
    os.makedirs("data", exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    # stamp spot onto the file so you can recompute moneyness later if needed
    surface = surface.copy()
    surface["spot"] = spot
    surface["snapshot_date"] = today
    path = f"data/surface_{today}.csv"
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
    surface.to_csv("surface.csv", index=False)

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