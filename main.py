import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq


#Black-Scholes Price of a European Option
#S     : spot price of the underlying
#K     : strike
#T     : time to expiry in YEARS (e.g. 30 days = 30/365)
#r     : risk-free rate (annual, decimal, e.g. 0.04)
#sigma : volatility (annual, decimal, e.g. 0.20)
#q     : continuous dividend yield (annual, decimal)
#cp    : "call" or "put"

def bs_price(S, K, T, r, sigma, q=0.0, cp="call"):
    d1 = (np.log(S/K) + (r - q + (sigma ** 2) / 2) * T ) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    if cp == "call":
        return S * np.exp(q * T * (-1)) * norm.cdf(d1) - K * np.exp(r * T * (-1)) * norm.cdf(d2) #call formula
    else:
        return K * np.exp(r * T * (-1)) * norm.cdf(d2 * -1) - S * np.exp(q * T * (-1)) * norm.cdf(d1 * -1) # put formula

def implied_vol(price, S, K, T, r, q=0.0, cp="call"):
    def f(sigma):
        return bs_price(S, K, T, r, sigma, q, cp) - price
    return brentq(f, 1e-6, 5.0) 



if __name__ == "__main__":
    # Test 1: known ATM value. S=K=100, T=1, r=0, sigma=0.2, no dividends.
    # The textbook answer is ~7.9656.
    p = bs_price(100, 100, 1.0, 0.0, 0.20, cp="call")
    print("Test 1 (price ~7.9656):", p, "->", np.isclose(p, 7.9656, atol=1e-3))

    # Test 2: put-call parity. C - P should equal S*e^(-qT) - K*e^(-rT).
    c = bs_price(100, 95, 0.5, 0.03, 0.25, cp="call")
    put = bs_price(100, 95, 0.5, 0.03, 0.25, cp="put")
    lhs = c - put
    rhs = 100 * np.exp(0) - 95 * np.exp(-0.03 * 0.5)
    print("Test 2 (parity holds):", np.isclose(lhs, rhs, atol=1e-6))

    # Test 3: round trip. Price at a known sigma, invert, recover that sigma.
    true_sigma = 0.30
    mkt = bs_price(100, 105, 0.75, 0.04, true_sigma, cp="call")
    recovered = implied_vol(mkt, 100, 105, 0.75, 0.04, cp="call")
    print("Test 3 (recover 0.30):", recovered, "->",
          np.isclose(recovered, true_sigma, atol=1e-6))