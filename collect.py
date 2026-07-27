#run once a day before and after FOMC July 28/29th
#
# Usage:
#   python collect.py                 -> data/surface_YYYY-MM-DD.csv
#   python collect.py --label pre     -> data/surface_YYYY-MM-DD_pre.csv
#
# The label lets you take more than one snapshot in a day without the second
# overwriting the first. On FOMC decision day, run with --label pre shortly
# before 2:00pm ET and --label post at the usual 3:00pm ET slot.

import argparse
import sys
from datetime import datetime

import yfinance as yf

from data import build_surface, save_daily_surface, ET

parser = argparse.ArgumentParser()
parser.add_argument("--label", default=None,
                    help="filename suffix, e.g. 'pre' or 'post'")
parser.add_argument("--force", action="store_true",
                    help="run even on a weekend")
args = parser.parse_args()

now = datetime.now(tz=ET)

if now.weekday() >= 5 and not args.force:   # 5 = Saturday, 6 = Sunday
    print("Weekend — market closed, skipping.")
    raise SystemExit(0)

spy = yf.Ticker("SPY")
hist = spy.history(period="1d")
if hist.empty:
    # non-zero exit so the wrapper script notices instead of committing nothing
    print("yfinance returned no data — likely rate-limited, wait and retry",
          file=sys.stderr)
    raise SystemExit(1)
spot = hist["Close"].iloc[-1]
print(f"{now.isoformat()}  SPY spot = {spot:.2f}")

surface = build_surface(spy, spot, now=now)
save_daily_surface(surface, spot, label=args.label, now=now)
