#!/usr/bin/env python3
"""Download public Binance market data for the paper-research crew.

Read-only: public endpoints, no API key, no trading calls.
Output: ./binance_data/ (CSV per symbol) and binance_data.tar.gz

Usage: python3 fetch_binance.py [--years 4] [--top 20]
Re-running only fetches candles newer than what is already on disk.
"""
import argparse, csv, json, os, tarfile, time, urllib.parse, urllib.request

SPOT = "https://data-api.binance.vision"   # public market-data mirror of api.binance.com
FUT = "https://fapi.binance.com"
STABLES = {"USDC", "FDUSD", "TUSD", "USDP", "DAI", "BUSD", "EUR", "USD1", "XUSD",
           "USDE", "AEUR", "EURI", "PYUSD", "BFUSD", "USDS", "UST", "PAXG"}
OUT = "binance_data"


def get(base, path, **params):
    url = f"{base}{path}?{urllib.parse.urlencode(params)}"
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # rate limit or network blip: back off and retry
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)


def top_symbols(n):
    rows = get(SPOT, "/api/v3/ticker/24hr")
    picks = []
    for r in rows:
        s = r["symbol"]
        if not s.endswith("USDT"):
            continue
        base = s[:-4]
        if base in STABLES or base.endswith(("UP", "DOWN", "BULL", "BEAR")):
            continue
        picks.append((float(r["quoteVolume"]), s))
    return [s for _, s in sorted(picks, reverse=True)[:n]]


def last_ts(path):
    if not os.path.exists(path):
        return None
    last = None
    with open(path) as f:
        for row in csv.reader(f):
            last = row
    return int(last[0]) if last and last[0].isdigit() else None


def fetch_klines(symbol, start_ms):
    path = os.path.join(OUT, f"{symbol}_1h.csv")
    prev = last_ts(path)
    new = prev is None
    header = not os.path.exists(path) or os.path.getsize(path) == 0
    cur = start_ms if new else prev + 1
    now = int(time.time() * 1000)
    n = 0
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if header:
            w.writerow(["open_time_ms", "open", "high", "low", "close", "volume",
                        "close_time_ms", "quote_volume", "trades"])
        while cur < now:
            batch = get(SPOT, "/api/v3/klines", symbol=symbol, interval="1h",
                        startTime=cur, limit=1000)
            # drop the candle that is still forming
            batch = [k for k in batch if k[6] < now]
            if not batch:
                break
            for k in batch:
                w.writerow(k[:9])
            n += len(batch)
            cur = batch[-1][0] + 1
            time.sleep(0.15)
    return n


def fetch_funding(symbol, start_ms):
    path = os.path.join(OUT, f"{symbol}_funding.csv")
    prev = last_ts(path)
    new = prev is None
    header = not os.path.exists(path) or os.path.getsize(path) == 0
    cur = start_ms if new else prev + 1
    n = 0
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if header:
            w.writerow(["funding_time_ms", "funding_rate"])
        while True:
            batch = get(FUT, "/fapi/v1/fundingRate", symbol=symbol,
                        startTime=cur, limit=1000)
            if not batch:
                break
            for r in batch:
                w.writerow([r["fundingTime"], r["fundingRate"]])
            n += len(batch)
            cur = batch[-1]["fundingTime"] + 1
            if len(batch) < 1000:
                break
            time.sleep(0.3)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=float, default=4)
    ap.add_argument("--top", type=int, default=20)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    start = int((time.time() - a.years * 365.25 * 86400) * 1000)

    meta_path = os.path.join(OUT, "meta.json")
    if os.path.exists(meta_path):  # keep the universe fixed across re-runs
        symbols = json.load(open(meta_path))["symbols"]
    else:
        symbols = top_symbols(a.top)

    report = {}
    for s in symbols:
        k = fetch_klines(s, start)
        try:
            fu = fetch_funding(s, start)
        except Exception as e:  # no perp for this symbol, or futures API blocked
            fu = f"unavailable: {e}"
        report[s] = {"new_1h_candles": k, "new_funding_rows": fu}
        print(s, report[s], flush=True)

    json.dump({"symbols": symbols, "source": [SPOT, FUT],
               "fetched_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "last_run": report}, open(meta_path, "w"), indent=1)
    with tarfile.open(OUT + ".tar.gz", "w:gz") as t:
        t.add(OUT)
    print("done ->", OUT + ".tar.gz")


if __name__ == "__main__":
    main()
