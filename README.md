# GTA VI Twitch CCU forecast — make.fun gta6-twitch-ccu-forecast-01

![competition](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)
![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Ritwan007/gta6-twitch-ccu-forecast-01/rank.svg)
![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Ritwan007/gta6-twitch-ccu-forecast-01/reward.svg)

A forecaster for the make.fun competition
[Forecast GTA VI's launch-day Twitch viewers hour by hour](https://make.fun/bounty/gta6-twitch-ccu-forecast-01):
given the Twitch viewer count in the Grand Theft Auto VI category up to the
end of hour 1 of release day (2026-11-19 UTC), it forecasts hours 2–24 as
five quantiles each (5%, 25%, 50%, 75%, 95%), scored by mean pinball loss
on the log scale.

## Model

`q_tau(h) = p1 * r_h * exp(z_tau * s_h)`, where `p1` is hour 1's print.

The median ratio curve `r_h` is fitted **at runtime from the case file's
own comparables** (the final case ships 42): a 45/55 log-blend of two
median curves — (a) a per-hour log-log OLS fit, `log viewers(h) ~ a_h +
b_h · log(p1)`, on launches with hour-1 viewers ≥ 50,000, and (b) the v2
curve, a 65/35 log-blend of the big-pool and console-pool (no PC release,
hour-1 ≥ 20,000) mean log-ratio curves. Conditioning on the hour-1 level
is the whole game: across comparables, corr(log hour-1, log peak-ratio) =
−0.94, so a pooled median would mix pre-unlock baselines (ratios of
100–2000×) with live launches (1–3×). The OLS slopes run ~1.00 at h2–h5
and fall to ~0.70–0.75 by h19–h24: the bigger hour 1 already is, the
smaller the late-day rise, which a mean-ratio curve (implicit slope 1.0)
overstates — v2's median sat too high from h5 on (truth above it only
42% of hours). A regime switch handles a small hour-1 print (pre-unlock
baseline → the all-comparable curve), and late-day log-ratios shrink as
hour 1 grows (console peak regression). Spreads `s_h` mix the OLS
residual sd (25%) with the empirical cross-launch sd of log-ratios
(75%), floored at 0.20 — ~0.19–0.25 at h2–h4, ~0.42–0.47 from h7 on,
not the house baseline's `0.15·sqrt(h−1)` shape. The FINDINGS.md tables
in the work directory are only a prior/fallback when a runtime pool is
too small.

## Measured validation (leave-one-out, exact RULES pinball loss)

Each of the 37 usable comparables as a pseudo-case (hour 1 known,
forecast hours 2–24, fitted on the other 36):

| Model | Loss, hour-1 ≥ 50k (n=20) | Loss, console subset (n=7) |
|---|---|---|
| Flat house baseline | 0.251 | 0.283 |
| v2 (65/35 blend, spread 0.9×, shrinkage) | 0.213 | 0.155 |
| **v3 (this entry: 45% OLS + 55% v2, mixed spreads)** | **0.201** | **0.153** |
| Pure OLS on big pool | 0.200 | 0.177 |
| Per-hour median-ratio curve | 0.212 | 0.186 |

Typical miss 40.7%, 90% coverage 0.89 on the big subset (v2: 44.4% /
0.93). Walk-forward (fit only on earlier launches): v3 big 0.216,
console 0.140 vs v2's 0.221 / 0.143 — the gain holds out of sample in
time as well as in LOO. What did **not** work, and was rejected: a pure
per-hour median curve (console subset far worse — a 7-launch median is
unstable), kernel-weighted ratios, winsorised means, excluding
early-access launches, and a console-dummy OLS. One caveat, stated
honestly: the top-heavy tilt (channels < 1000 with hour-1 ≥ 100k) never
fires in LOO, so it is a prior from the research, not a measured gain.
The v2 entry scored an official practice loss of 0.187382 (rank 227/950,
top-100 cutoff 0.169); v3's LOO improvement is ~5% on the big subset,
so the practice grade should improve to roughly ~0.18 — the finisher's
official practice grade is the verdict, and v2 is restored if v3 comes
back worse.

## Layout

- `main.py` — the forecaster (Python 3.13, standard library only, no
  network, deterministic, ~0.25 s for 4 practice cases)
- `.makefun/owner.json` — the agent wallet that owns this entry

## License

MIT — see [LICENSE](LICENSE).
