#run once a day before and after FOMC July 28/29th

import yfinance as yf
from datetime import datetime
from data import build_surface, save_daily_surface  # import your functions

if datetime.now().weekday() >= 5:      # 5 = Saturday, 6 = Sunday
    print("Weekend — market closed, skipping.")
    raise SystemExit

spy = yf.Ticker("SPY")
hist = spy.history(period="1d")
if hist.empty:
    raise RuntimeError("yfinance returned no data — wait and retry")
spot = hist["Close"].iloc[-1]

surface = build_surface(spy, spot)
save_daily_surface(surface, spot)