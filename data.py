import yfinance as yf
import pandas as pd

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
