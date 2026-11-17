"""Forecast GTA VI launch-day Twitch viewers, hours 2-24, as five quantiles.

Model (fitted at runtime from the case file's own comparables; the tables
below are only a prior/fallback when a pool is too small to fit):

  q_tau(h) = p1 * r_h * exp(z_tau * s_h)

where p1 is hour 1's print. The median ratio r_h is the mean log-ratio
curve of past big launches, conditioned on the hour-1 level -- the single
strongest fact in the data is corr(log hour-1, log peak-ratio) = -0.94, so
a pooled median over all launches is useless: tiny pre-unlock hour-1
prints (ratios of 100-2000x) must never be averaged with live launches
(ratios of 1-3x).

Pools, computed from the case's comparables at runtime:
  * big pool     -- hour-1 viewers >= 50,000 (the live-launch regime)
  * console pool -- no PC release, hour-1 viewers >= 20,000 (rolling
    midnight console launches; GTA VI's own class: PS5/Xbox only)
  * all pool     -- every comparable with a usable release day
The median curve is a 65/35 log-blend of the big and console mean-log
curves (blend weight 0.35 on console). Leave-one-out over the 37
comparables (each as a pseudo-case, fitted on the other 36, exact RULES
pinball loss) measured: flat house baseline 0.251 on the hour-1 >= 50k
subset and 0.283 on the console subset; this model 0.213 and 0.155.
A 50/50 blend scored 0.218 / 0.158, big-pool-only 0.209 / 0.172, so
0.35 keeps nearly all of the console-class gain while giving back most
of the big-pool loss. Walk-forward (fit only on earlier launches) moves
both subset losses by < 0.01, so the curve is not era-sensitive.

Regime switch on p1: below 20k hour 1 is a pre-unlock baseline, so the
all-pool curve applies; 20k-50k interpolates in log space between the
all curve and the blend; at/above 50k the blend applies, with late-day
log-ratios shrunk as hour 1 grows (peak ratio falls as hour 1 rises:
log peak ratio ~ 4.32 - 0.71*log10(hour-1) on console launches).

Spreads s_h are the cross-launch dispersion of log-ratios, roughly flat
across the day (~0.38-0.45 after the 0.9 calibration multiplier),
NOT the house baseline's 0.15*sqrt(h-1) shape, which is far too narrow
early and far too wide late. The 0.9 multiplier is LOO-measured: it
improves the console subset (0.155 vs 0.158 at 1.0) with no cost on
the big subset, and keeps 90% coverage at 0.91-0.93.

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

# Prior median ratios r_h for h = 2..24 (FINDINGS §5.1, 50/50 log-blend of
# the big-pool and console-pool mean log-ratio curves). Used only when a
# runtime pool is too small to fit; the fitted curve replaces them.
PRIOR_BLEND = [
    0.89, 0.69, 0.63, 0.79, 0.84, 0.79, 0.77, 0.76, 0.75, 0.77, 0.84,
    0.98, 1.13, 1.32, 1.43, 1.52, 1.62, 1.73, 1.77, 1.78, 1.71, 1.58,
    1.46,
]
# Prior all-comparable median ratios (FINDINGS §2.2), for the pre-unlock
# regime (p1 < 20k), where hour 1 carries no scale information.
PRIOR_ALL = [
    0.87, 0.75, 0.73, 0.75, 0.79, 0.80, 0.90, 0.88, 0.91, 0.93, 0.98,
    1.06, 1.18, 1.52, 1.65, 1.77, 1.95, 2.40, 2.37, 2.33, 2.30, 2.18,
    2.04,
]

# Log-spread s_h by hour band: roughly flat cross-launch dispersion.
SPREAD_BANDS = [(2, 6, 0.42), (7, 12, 0.45), (13, 18, 0.47), (19, 24, 0.50)]

# LOO-chosen defaults (see module docstring): blend_w 0.35, spread 0.9x.
DEFAULT_CFG = {"blend_w": 0.35, "spread_mult": 0.9, "shrink": True, "tilt": True}


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


def spread_for(hour, mult):
    for lo, hi, s in SPREAD_BANDS:
        if lo <= hour <= hi:
            return s * mult
    return 0.50 * mult


def build_log_ratios(p1, channels, top_share, comparables, cfg):
    """Median log-ratio curve (hours 2..24) plus per-hour spreads."""
    days = []
    for comp in comparables or []:
        day = release_day_viewers(comp)
        if day is None:
            continue
        platforms = comp.get("platforms") or ""
        days.append((day, "PC" not in platforms))
    big = [d for d, _ in days if d[0] >= 50000]
    console = [d for d, is_console in days if is_console and d[0] >= 20000]
    all_days = [d for d, _ in days]

    w = cfg["blend_w"]
    if len(big) >= 8 and len(console) >= 4:
        big_curve = mean_log_curve(big)
        console_curve = mean_log_curve(console)
        blend = [(1 - w) * b + w * c for b, c in zip(big_curve, console_curve)]
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

    # Shrinkage of late-day log-ratios as hour 1 grows (console peak
    # regression: log peak ratio falls with log10(hour-1)).
    if cfg["shrink"]:
        g = 1.0 - 0.25 * math.log10(max(p1, 1) / 100000.0)
        g = min(1.0, max(0.6, g))
        log_r = [v * g if h >= 13 else v for h, v in zip(HOURS, log_r)]

    # Top-heavy tilt: few channels carrying a huge hour 1 means small
    # streamers still join through the day; lift the afternoon/evening.
    if cfg["tilt"] and channels is not None and channels < 1000 and p1 >= 100000:
        log_r = [v + 0.1 if h >= 15 else v for h, v in zip(HOURS, log_r)]

    spreads = [spread_for(h, cfg["spread_mult"]) for h in HOURS]
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

    log_r, spreads = build_log_ratios(
        p1, channels, top_share, case.get("comparables"), cfg
    )
    rows = []
    for h, lr, s in zip(HOURS, log_r, spreads):
        median = p1 * math.exp(lr)
        qs = [round2(median * math.exp(z * s)) for z in Z]
        # Guard the contract: finite, > 0, <= 1e9, non-decreasing.
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
