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

def bs_delta(S, K, T, r, sigma, q=0.0, cp="call"):
    """Black-Scholes delta. Signed: calls in (0, 1), puts in (-1, 0).

    Needed for the 25-delta skew metric — the standard way desks quote skew is
    put IV minus call IV at equal-and-opposite delta, not at equal strike.
    """
    d1 = (np.log(S/K) + (r - q + (sigma ** 2) / 2) * T) / (sigma * np.sqrt(T))
    if cp == "call":
        return np.exp(-q * T) * norm.cdf(d1)
    else:
        return -np.exp(-q * T) * norm.cdf(-d1)

def implied_vol(price, S, K, T, r, q=0.0, cp="call"):
    def f(sigma):
        return bs_price(S, K, T, r, sigma, q, cp) - price
    return brentq(f, 1e-6, 5.0)



if __name__ == "__main__":
    # Assertions, not prints — a printed test can't fail, and a silent bug in
    # the mid-price calc already slipped through once.

    # Test 1: known ATM value. S=K=100, T=1, r=0, sigma=0.2, no dividends.
    # The textbook answer is ~7.9656.
    p = bs_price(100, 100, 1.0, 0.0, 0.20, cp="call")
    assert np.isclose(p, 7.9656, atol=1e-3), f"ATM price {p}, expected ~7.9656"

    # Test 2: put-call parity. C - P should equal S*e^(-qT) - K*e^(-rT).
    c = bs_price(100, 95, 0.5, 0.03, 0.25, cp="call")
    put = bs_price(100, 95, 0.5, 0.03, 0.25, cp="put")
    lhs = c - put
    rhs = 100 * np.exp(0) - 95 * np.exp(-0.03 * 0.5)
    assert np.isclose(lhs, rhs, atol=1e-6), f"parity broken: {lhs} vs {rhs}"

    # Test 3: round trip. Price at a known sigma, invert, recover that sigma.
    true_sigma = 0.30
    mkt = bs_price(100, 105, 0.75, 0.04, true_sigma, cp="call")
    recovered = implied_vol(mkt, 100, 105, 0.75, 0.04, cp="call")
    assert np.isclose(recovered, true_sigma, atol=1e-6), \
        f"recovered {recovered}, expected {true_sigma}"

    # Test 4: delta bounds and put-call delta parity.
    # call_delta - put_delta = e^(-qT) for the same strike.
    cd = bs_delta(100, 105, 0.75, 0.04, 0.30, q=0.012, cp="call")
    pd_ = bs_delta(100, 105, 0.75, 0.04, 0.30, q=0.012, cp="put")
    assert 0 < cd < 1 and -1 < pd_ < 0, f"delta out of bounds: {cd}, {pd_}"
    assert np.isclose(cd - pd_, np.exp(-0.012 * 0.75), atol=1e-9), \
        "call/put delta parity broken"

    # Test 5: a deep ITM call should have delta near 1, deep OTM near 0.
    assert bs_delta(100, 10, 1.0, 0.04, 0.20, cp="call") > 0.99
    assert bs_delta(100, 500, 1.0, 0.04, 0.20, cp="call") < 0.01

    print("All pricer tests passed.")