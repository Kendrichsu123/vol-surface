import yfinance as yf
import pandas as pd
from main import implied_vol
from datetime import datetime

TICKER = "SPY"

spy = yf.Ticker(TICKER)

expirations = spy.options
print("Available expirations:")
print(expirations)
print()

expiry = expirations[11]
print("Using expiry:", expiry)
print()

chain = spy.option_chain(expiry)
calls = chain.calls
puts = chain.puts

print("Calls shape:", calls.shape)
print(calls.head())
print()
print("Puts shape:", puts.shape)
print(puts.head())
print()

print("Columns available:")
print(calls.columns.tolist())

near = calls[(calls["strike"] > 730) & (calls["strike"] < 770)]
print(near[["strike", "bid", "ask", "volume", "openInterest", "impliedVolatility"]])

spot = spy.history(period="1d")["Close"].iloc[-1]
print("Spot price:", spot)
print()

calls["mid"] = (calls["bid"] + calls["ask"]) / 2
puts["mid"] = (puts["bid"] + puts["ask"]) / 2

near_calls = calls[(calls["strike"] > 730) & (calls["strike"] < 770)]
print(near_calls[["strike", "bid", "ask", "mid"]])

otm_calls = calls[(calls["strike"] > spot) & (calls["bid"] > 0) 
                  & ((calls["ask"] - calls["bid"]) / calls["mid"] < 0.5) & (calls["openInterest"] > 0)]
otm_puts = puts[(puts["strike"] < spot) & (puts["bid"] > 0) 
                & ((puts["ask"] - puts["bid"]) / puts["mid"] < 0.5) & (puts["openInterest"] > 0)]

print(f"Calls: {len(calls)} -> {len(otm_calls)} after filtering")
print(f"Puts:  {len(puts)} -> {len(otm_puts)} after filtering")

r = 0.045 #risk-free rate
q = 0.012 #SPY dividend rate

expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
today = datetime.now().date()
T = (expiry_date - today).days / 365
print("T (years):", T)

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
    
# 3. Apply it across each table.
#    .apply(..., axis=1) runs the function on each row.
otm_calls = otm_calls.copy()
otm_puts  = otm_puts.copy()
otm_calls["iv"] = otm_calls.apply(lambda row: compute_iv(row, "call"), axis=1)
otm_puts["iv"]  = otm_puts.apply(lambda row: compute_iv(row, "put"), axis=1)

# 4. Drop rows where IV came back None (brentq failed on that quote).
otm_calls = otm_calls[otm_calls["iv"].notna()]
otm_puts  = otm_puts[otm_puts["iv"].notna()]

# 5. Compare your IV against yfinance's own — should be close.
print(otm_calls[["strike", "mid", "iv", "impliedVolatility"]].head(10).to_string())
print(otm_puts[["strike", "mid", "iv", "impliedVolatility"]].head(10).to_string())

print(f"Calls with valid IV: {len(otm_calls)}")
print(f"Puts with valid IV:  {len(otm_puts)}")