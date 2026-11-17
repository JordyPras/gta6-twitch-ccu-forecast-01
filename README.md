# gta6-twitch-ccu-forecast-01

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/JordyPras/gta6-twitch-ccu-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/JordyPras/gta6-twitch-ccu-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

A program that forecasts GTA VI's launch-day Twitch viewers hour by hour (hours 2–24) from the first hour's print and the launch-day shapes of 38+ comparable past game launches. For each comparable it computes per-hour log ratios to that launch's own hour-1 count, filters out early-access, weak and simultaneous-unlock analogues, fits a weighted regression of each hour's log ratio on the log hour-1 count, and reads the fit at the target case's hour-1 print, with leverage-adjusted quantile bands calibrated on the practice cases and leave-one-out runs. Python standard library only, deterministic, no network, no model calls.

## Run it

```sh
MAKEFUN_INPUT_DIR=./input MAKEFUN_OUTPUT_DIR=./output python3 main.py
```

Reads every `*.in` case file in `$MAKEFUN_INPUT_DIR` (default `/input/`) and writes one `<id>.out` forecast per case to `$MAKEFUN_OUTPUT_DIR` (default `/output/`). Each output is exactly `{"hours": [{hour, q: [q05, q25, q50, q75, q95]}]}` for hours 2–24. See BUILD-NOTES.md for the approach and validation results.

---

<sub>Entered on [make.fun](https://make.fun/?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
