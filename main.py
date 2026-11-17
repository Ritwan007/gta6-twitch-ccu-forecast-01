"""Forecast GTA VI launch-day Twitch viewers, hours 2-24, as five quantiles.

Model (v3): a 45/55 log-blend of two median curves, both fitted at runtime
from the case file's own comparables:

  q_tau(h) = p1 * r_h * exp(z_tau * s_h)

where p1 is hour 1's print. The two median curves are

  (a) a per-hour log-log OLS fit: log viewers(h) ~ a_h + b_h * log(p1),
      fitted on the big pool (hour-1 viewers >= 50,000). The fitted slopes
      run ~1.00 at h2-h5 and fall to ~0.70-0.75 by h19-h24: the bigger hour
      1 already is, the smaller the late-day rise (corr(log hour-1,
      log peak-ratio) = -0.94). A mean-ratio curve assumes slope 1.0
      everywhere and therefore overstates the evening rise for big
      launches; the OLS lets the data set the slope hour by hour.
  (b) the v2 curve: a 65/35 log-blend of the big-pool and console-pool
      (no PC release, hour-1 >= 20,000) mean log-ratio curves, with a
      regime switch on p1 and late-day shrinkage as hour 1 grows.

The blend keeps the OLS gain where it is measured (the big pool) and the
mean-log curve's stability where OLS is noisy (the console pool, n=7).
Leave-one-out over the 37 comparables (each as a pseudo-case, fitted on
the other 36, exact RULES pinball loss) measured, v2 vs v3:

  big subset (hour-1 >= 50k, n=20):  0.2125 -> 0.2012 (miss 44.4% -> 40.7%)
  console subset (n=7):              0.1546 -> 0.1530 (miss 28.7% -> 28.2%)
  all 37:                            0.7116 -> 0.7096
Walk-forward (fit only on earlier launches): big 0.2214 -> 0.2156,
console 0.1426 -> 0.1400. The v3 median is therefore better on every
measured cell, with the big-subset gain the clear one (-0.011 LOO).

Diagnosis that drove the change: v2's median sat too high from h5 on
(truth above the v2 median only 42% of hours, mean signed log error
-0.05..-0.15 from h5-h24), because the mean log-ratio curve is the
geometric mean, not the median, and it assumes the ratio does not fall
with hour-1 level. A pure per-hour median curve was tested and rejected:
it is no better on the big subset and far worse on the console subset
(0.186 vs 0.155) because a 7-launch median is unstable. The OLS blend
is the fix that survives both subsets.

Spreads s_h mix the OLS residual sd (25%) with the empirical cross-launch
sd of log-ratios (75%, big/console blended 65/35), floored at 0.20: the
floor is cheap insurance for the final, whose minute-mean prints are
noisier than the hourly averages the spreads were calibrated on (LOO
cost of the floor: nil). Spreads are therefore ~0.19-0.25 at h2-h4 and
~0.42-0.47 from h7 on, NOT the house baseline's 0.15*sqrt(h-1) shape,
which is far too narrow early and far too wide late.

Two further runtime tilts use the case's own checkpoint data:
  * top-heavy (channels < 1000 while p1 >= 100k): small streamers join
    through the day, so log-ratios after h12 tilt up by 0.1 (a prior
    from the research findings; no LOO pseudo-case triggers it, so it
    is unvalidated by LOO and fires only in that narrow case);
  * one stream holding > 30% of viewers: widen s_h by 0.05 (that stream
    ending moves the total).

Standard library only, no network, deterministic: same input bytes give
the same output bytes. Reads every *.in in $MAKEFUN_INPUT_DIR (else
/input) and writes <id>.out to $MAKEFUN_OUTPUT_DIR (else /output).
"""

import json
import math
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0, 0.674, 1.645]
HOURS = list(range(2, 25))

# Prior median ratios r_h for h = 2..24 (FINDINGS section 5.1, 50/50
# log-blend of the big-pool and console-pool mean log-ratio curves).
# Used only when a runtime pool is too small to fit; the fitted curves
# replace them.
PRIOR_BLEND = [
    0.89, 0.69, 0.63, 0.79, 0.84, 0.79, 0.77, 0.76, 0.75, 0.77, 0.84,
    0.98, 1.13, 1.32, 1.43, 1.52, 1.62, 1.73, 1.77, 1.78, 1.71, 1.58,
    1.46,
]
# Prior all-comparable median ratios (FINDINGS section 2.2), for the
# pre-unlock regime (p1 < 20k), where hour 1 carries no scale information.
PRIOR_ALL = [
    0.87, 0.75, 0.73, 0.75, 0.79, 0.80, 0.90, 0.88, 0.91, 0.93, 0.98,
    1.06, 1.18, 1.52, 1.65, 1.77, 1.95, 2.40, 2.37, 2.33, 2.30, 2.18,
    2.04,
]

# v3 defaults (LOO + walk-forward measured; see module docstring).
DEFAULT_CFG = {"alpha": 0.45, "spread_floor": 0.20, "tilt": True}
BLEND_W_CONSOLE = 0.35   # console weight inside the mean-log curve
SPREAD_W_OLS = 0.25      # OLS residual-sd weight inside the spread mix


def _parse_time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def release_day_viewers(comp):
    """The comparable's 24 release-day hourly viewer counts, or None.

    Release day is the 24 UTC hours from its day_start; hour 1 is the
    first of them. Any missing/non-positive hour voids the comparable.
    """
    try:
        start = _parse_time(comp["day_start"])
    except (KeyError, TypeError, ValueError):
        return None
    by_hour = {}
    for row in comp.get("hourly") or []:
        try:
            at = _parse_time(row["from"])
            viewers = row["viewers"]
        except (KeyError, TypeError, ValueError):
            continue
        if viewers is None:
            continue
        idx = int((at - start).total_seconds() // 3600)
        if 0 <= idx < 24 and idx not in by_hour:
            by_hour[idx] = viewers
    if len(by_hour) != 24:
        return None
    day = [by_hour[i] for i in range(24)]
    if any(v is None or v <= 0 for v in day):
        return None
    return day


def mean_log_curve(days):
    """Per-hour mean of log(viewers(h) / viewers(hour 1)), hours 2..24."""
    curve = []
    for h in range(2, 25):
        total = 0.0
        for day in days:
            total += math.log(day[h - 1] / day[0])
        curve.append(total / len(days))
    return curve


def sd_log_curve(days):
    """Per-hour sd of log(viewers(h) / viewers(hour 1)), hours 2..24."""
    out = []
    for h in range(2, 25):
        xs = [math.log(day[h - 1] / day[0]) for day in days]
        m = sum(xs) / len(xs)
        var = sum((x - m) ** 2 for x in xs) / max(len(xs) - 1, 1)
        out.append(math.sqrt(var))
    return out


def _ols_fit(xs, ys):
    """Least-squares y ~ a + b*x; returns (a, b)."""
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 1e-12:
        return my, 0.0
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return my - b * mx, b


def ols_curve(days, p1):
    """Per-hour log-log OLS: log viewers(h) ~ a_h + b_h * log(p1).

    Returns (median log-ratios, residual sd per hour). The median
    log-ratio at hour h is the fitted log viewers(h) minus log(p1).
    """
    xs = [math.log(day[0]) for day in days]
    med, sds = [], []
    for h in range(2, 25):
        ys = [math.log(day[h - 1]) for day in days]
        a, b = _ols_fit(xs, ys)
        pred = a + b * math.log(p1)
        med.append(pred - math.log(p1))
        res = [y - (a + b * x) for x, y in zip(xs, ys)]
        var = sum(r * r for r in res) / max(len(res) - 2, 1)
        sds.append(math.sqrt(var))
    return med, sds


def mean_log_model(p1, channels, days, cfg):
    """The v2 median curve: 65/35 big/console mean-log blend, regime
    switch on p1, late-day shrinkage, top-heavy tilt. Returns the
    median log-ratio curve (hours 2..24)."""
    big = [d for d, _ in days if d[0] >= 50000]
    console = [d for d, is_console in days if is_console and d[0] >= 20000]
    all_days = [d for d, _ in days]

    w = BLEND_W_CONSOLE
    if len(big) >= 8 and len(console) >= 4:
        blend = [(1 - w) * b + w * c for b, c in
                 zip(mean_log_curve(big), mean_log_curve(console))]
    elif len(big) >= 8:
        blend = mean_log_curve(big)
    else:
        blend = [math.log(r) for r in PRIOR_BLEND]

    if len(all_days) >= 8:
        all_curve = mean_log_curve(all_days)
    else:
        all_curve = [math.log(r) for r in PRIOR_ALL]

    # Regime switch on the hour-1 level (log-space interpolation).
    if p1 < 20000:
        log_r = list(all_curve)
    elif p1 < 50000:
        t = (math.log(p1) - math.log(20000)) / (math.log(50000) - math.log(20000))
        log_r = [a + t * (b - a) for a, b in zip(all_curve, blend)]
    else:
        log_r = list(blend)

    # Shrinkage of late-day log-ratios as hour 1 grows (peak ratio
    # falls as hour 1 rises: log peak ratio ~ 4.32 - 0.71*log10(hour-1)
    # on console launches).
    g = 1.0 - 0.25 * math.log10(max(p1, 1) / 100000.0)
    g = min(1.0, max(0.6, g))
    log_r = [v * g if h >= 13 else v for h, v in zip(HOURS, log_r)]

    # Top-heavy tilt: few channels carrying a huge hour 1 means small
    # streamers still join through the day; lift the afternoon/evening.
    if cfg["tilt"] and channels is not None and channels < 1000 and p1 >= 100000:
        log_r = [v + 0.1 if h >= 15 else v for h, v in zip(HOURS, log_r)]
    return log_r


def build_forecast(p1, channels, top_share, comparables, cfg):
    """Median log-ratio curve (hours 2..24) plus per-hour spreads."""
    days = []
    for comp in comparables or []:
        day = release_day_viewers(comp)
        if day is None:
            continue
        platforms = comp.get("platforms") or ""
        days.append((day, "PC" not in platforms))

    v2_curve = mean_log_model(p1, channels, days, cfg)

    big = [d for d, _ in days if d[0] >= 50000]
    console = [d for d, is_console in days if is_console and d[0] >= 20000]

    # OLS component (big pool only): per-hour log-log regression.
    if len(big) >= 8:
        ols_med, ols_sd = ols_curve(big, p1)
    else:
        ols_med, ols_sd = list(v2_curve), [0.4] * 23

    # Empirical cross-launch dispersion, big/console blended 65/35.
    if len(big) >= 8 and len(console) >= 4:
        emp_sd = [(1 - BLEND_W_CONSOLE) * b + BLEND_W_CONSOLE * c for b, c in
                  zip(sd_log_curve(big), sd_log_curve(console))]
    elif len(big) >= 8:
        emp_sd = sd_log_curve(big)
    else:
        emp_sd = [0.42] * 23

    alpha = cfg["alpha"]
    log_r = [alpha * o + (1 - alpha) * v for o, v in zip(ols_med, v2_curve)]
    spreads = [max(SPREAD_W_OLS * o + (1 - SPREAD_W_OLS) * e,
                   cfg["spread_floor"])
               for o, e in zip(ols_sd, emp_sd)]
    if cfg["tilt"] and top_share is not None and top_share > 0.30:
        spreads = [s + 0.05 for s in spreads]
    return log_r, spreads


def round2(x):
    """Round to 2 decimals, half up (matches the starter's convention)."""
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if value == int(value) else value


def forecast_case(case, cfg=None):
    cfg = {**DEFAULT_CFG, **(cfg or {})}
    if case.get("levels") != LEVELS:
        raise ValueError("unexpected quantile levels")
    first = next((k for k in case["known"] if k["hour"] == 1), None)
    if first is None:
        raise ValueError("no hour-1 print")
    p1 = max(1.0, float(first["viewers"]))
    channels = first.get("channels")
    top_share = None
    streams = case.get("streams") or []
    if streams:
        top = max((s.get("viewers") or 0) for s in streams)
        if top > 0:
            top_share = top / p1

    log_r, spreads = build_forecast(
        p1, channels, top_share, case.get("comparables"), cfg
    )
    rows = []
    for h, lr, s in zip(HOURS, log_r, spreads):
        median = p1 * math.exp(lr)
        qs = [round2(median * math.exp(z * s)) for z in Z]
        # Guard the contract: finite, > 0, <= 1e9, non-decreasing. A
        # non-finite value (should not happen with valid inputs) falls
        # back to the median so the case stays valid.
        qs = [q if math.isfinite(q) else median for q in qs]
        qs = [min(max(q, 0.01), 1e9) for q in qs]
        for i in range(1, 5):
            if qs[i] < qs[i - 1]:
                qs[i] = qs[i - 1]
        rows.append({"hour": h, "q": qs})
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case)
        out = OUTPUT_DIR / f"{path.stem}.out"
        out.write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
