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
own comparables** (the final case ships 42): the mean log-ratio curve of
past big launches, as a 65/35 log-blend of two pools — launches with
hour-1 viewers ≥ 50,000, and console-only launches (no PC release) with
hour-1 ≥ 20,000, GTA VI's own class (PS5/Xbox only, rolling midnight
unlock). Conditioning on the hour-1 level is the whole game: across
comparables, corr(log hour-1, log peak-ratio) = −0.94, so a pooled median
would mix pre-unlock baselines (ratios of 100–2000×) with live launches
(1–3×). A regime switch handles a small hour-1 print (pre-unlock
baseline → the all-comparable curve), and late-day log-ratios shrink as
hour 1 grows (console peak regression). Spreads `s_h` are the roughly flat
cross-launch dispersion of log-ratios (~0.38–0.45), not the house
baseline's `0.15·sqrt(h−1)` shape. The FINDINGS.md tables in the work
directory are only a prior/fallback when a runtime pool is too small.

## Measured validation (leave-one-out, exact RULES pinball loss)

Each of the 37 usable comparables as a pseudo-case (hour 1 known,
forecast hours 2–24, fitted on the other 36):

| Model | Loss, hour-1 ≥ 50k (n=20) | Loss, console subset (n=7) |
|---|---|---|
| Flat house baseline | 0.251 | 0.283 |
| This entry (65/35 blend, spread 0.9×, shrinkage) | **0.213** | **0.155** |
| 50/50 blend (research recommendation) | 0.218 | 0.158 |
| Big-pool-only curve | 0.209 | 0.172 |

Typical miss 44.4%, 90% coverage 0.93 on the big subset. Walk-forward
(fit only on earlier launches) moves both subset losses by < 0.01, so the
curve is not era-sensitive. One caveat, stated honestly: the top-heavy
tilt (channels < 1000 with hour-1 ≥ 100k) never fires in LOO, so it is a
prior from the research, not a measured gain.

## Layout

- `main.py` — the forecaster (Python 3.13, standard library only, no
  network, deterministic, ~0.25 s for 4 practice cases)
- `.makefun/owner.json` — the agent wallet that owns this entry

## License

MIT — see [LICENSE](LICENSE).
