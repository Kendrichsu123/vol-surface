import yfinance as yf
import pandas as pd
import numpy as np
from main import implied_vol
from datetime import datetime
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa

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


spy = yf.Ticker(TICKER)
hist = spy.history(period="1d")
if hist.empty:
    raise RuntimeError("yfinance returned no price data for SPY — likely rate-limited, wait and retry")
spot = hist["Close"].iloc[-1]

all_smiles = []
for exp in spy.options[:40:3]:
    result = smile_for_expiry(spy, exp, spot)
    if result is not None and len(result) > 0:
        all_smiles.append(result)
        print(f"{exp}: {len(result)} points")

surface = pd.concat(all_smiles, ignore_index = True)

fig = plt.figure(figsize=(12, 8))
ax = fig.add_subplot(111, projection="3d")
ax.scatter(surface["log_moneyness"], surface["T"], surface["iv"],
           c=surface["iv"], cmap="viridis", s=10)
ax.set_xlabel("Log-moneyness ln(K/S)")
ax.set_ylabel("Time to expiry (years)")
ax.set_zlabel("Implied volatility")
ax.set_title("SPY Implied Volatility Surface")
plt.savefig("surface.png", dpi=150, bbox_inches="tight") 
surface.to_csv("surface.csv", index=False) 
plt.show()
plt.close()

surface["m_bin"] = pd.cut(surface["log_moneyness"], bins=30)

# 2. Also round T so near-identical expiries group cleanly as rows.
#    (Each expiry already has a distinct T, so this is mostly cosmetic,
#     but rounding avoids floating-point near-duplicates.)
surface["T_round"] = surface["T"].round(3)

# 3. Pivot into a grid: rows = T, columns = moneyness bucket, values = IV.
#    pivot_table averages IV when multiple points share a cell.
grid = surface.pivot_table(
    index="T_round",
    columns="m_bin",
    values="iv",
    aggfunc="mean",
    observed=False,
)

# 4. Plot the grid as a heatmap.
plt.figure(figsize=(12, 7))
plt.imshow(
    grid.values,
    aspect="auto",
    origin="lower",
    cmap="viridis",
)
plt.colorbar(label="Implied volatility")
plt.xlabel("Log-moneyness bucket (low strike → high strike)")
plt.ylabel("Time to expiry index (near → far)")
plt.title("SPY Implied Volatility Surface — heatmap")
plt.savefig("heatmap.png", dpi=150, bbox_inches="tight")
plt.show()