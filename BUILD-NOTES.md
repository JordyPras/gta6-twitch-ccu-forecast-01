# Build notes — gta6-twitch-ccu-forecast-01

## What it does

`main.py` reads every `*.in` case file in `$MAKEFUN_INPUT_DIR` (else `/input/`)
and writes one `<id>.out` forecast per case to `$MAKEFUN_OUTPUT_DIR` (else
`/output/`): exactly `{"hours": [{hour, q: [q05, q25, q50, q75, q95]}]}` for
hours 2–24. Python standard library only, no network, no model calls, no
randomness — the same input always produces byte-identical output.

## Approach

1. **Comparable log-ratio curves.** For each comparable, take its release
   day's 24 hourly counts and express hours 2–24 as log ratios to its own
   hour-1 count: `r_h = ln(viewers_h / viewers_1)`. A comparable with no
   usable hour-1 count is skipped (this removes the target's own pre-release
   history, which is not a launch).
2. **Trust filter from the unlock notes.** Early-access-contaminated launches
   (hour 1 is already day 4 of play), weak analogues (free-to-play,
   slow-burn), and simultaneous global unlocks (near-empty hour 1, ratios
   explode) get weight 0. Rolling midnight-local launches — GTA VI's own
   pattern — get weight 1.5; other clean comparables weight 1.0. In the
   practice cases this leaves 22 trusted curves.
3. **Scale regression.** Across clean rolling launches, each hour's log ratio
   falls almost linearly with the log hour-1 count (correlation −0.92 for the
   peak ratio: a launch whose first hour already drew 800k cannot triple by
   the evening; one whose first hour drew 25k usually does). For each hour,
   weighted least squares of `r_h` on `ln(hour-1)` over the trusted curves,
   read at the target's own `ln(hour-1 print)`, clamped to the range of
   ratios the comparables actually showed that hour, plus absolute sanity
   guardrails (no hour below 2% or above 50× of hour 1).
4. **Quantile bands.** Fitted value plus normal-quantile offsets times the
   hour's residual spread, widened by the prediction's leverage (so an
   hour-1 print far outside the comparables' range gets a wider band), times
   a calibration factor of 0.65 chosen on the practice cases and on
   leave-one-out runs (see below).
5. **Fallbacks, always valid.** Too few trusted comparables → fit on every
   comparable with an hour 1 → per-hour median ratio with a fixed spread →
   persistence forecast. Any unexpected error anywhere → persistence
   forecast from the hour-1 print alone. Every output row is guarded:
   finite, > 0, ≤ 1e9, non-decreasing.

## Validation

Ground truth for the 4 practice cases was taken from the SullyGnome
endpoints documented in the kit's `input/NOTICE.txt` (GameViewers "Average
viewers" datasets; verified by exact hour-1 match in all 4 cases) and scored
with the pinball loss exactly as RULES.txt defines it (mean over every
hour × quantile, log scale). The starter baseline run the same way scores
0.3871, matching the house figure of ~0.387.

| case | game | this entry | starter baseline |
|------|------|-----------|------------------|
| p00 | Marvel's Wolverine | 0.1427 | 0.7437 |
| p01 | Red Dead Redemption 2 | 0.1519 | 0.2868 |
| p02 | God of War Ragnarök | 0.1534 | 0.2146 |
| p03 | Marvel's Spider-Man 2 | 0.1972 | 0.3033 |
| **mean** | | **0.1613** | **0.3871** |

Typical miss (median absolute log error): 16.7% / 23.3% / 24.6% / 31.9%
(baseline ~82.8%). 90% band coverage: 0.957 / 0.957 / 1.000 / 0.826
(mean 0.935, close to the nominal 0.90).

**Leave-one-out over comparables** (restricted to clean, non-simultaneous
launches with hour-1 ≥ 10k, n=18): mean loss 0.2756, coverage 0.831 at the
chosen 0.65 spread — the spread balances practice (which prefers ~0.55)
against leave-one-out coverage (which prefers ~0.7). Schemes tried and
rejected on these measurements: unweighted ratio quantiles (0.324),
tier+pattern empirical quantiles (0.294), rolling-only fit (0.160 practice
but 0.837 coverage, worse on p03), recency weighting (0.170), a jump
predictor from the pre-release median (0.19–0.20 practice, 0.295 LOO-R),
empirical residual quantiles instead of normal bands (0.172 practice,
0.282 LOO-R), and a peak/h1 > 20 filter on the fit set (0.167 practice,
coverage 0.804).

**Determinism:** each practice case run twice, outputs byte-identical.
**Timing:** all 4 cases in 0.18 s total on a 1.5-CPU VM (limit is 8 s per
case). **Edge cases** (10 synthetic cases, all produced valid output, none
crashed): tiny hour-1 print (10), zero hour-1 print, empty comparables,
missing `known`/`history`/`forecast`, a single comparable, all comparables
simultaneous, malformed JSON input, a 2.5M hour-1 print, and sparse
comparable hours.

## Run it locally

```sh
MAKEFUN_INPUT_DIR=./input MAKEFUN_OUTPUT_DIR=./output python3 main.py
```

The kit's practice cases live in the unpacked kit's `input/` directory.
Requires Python 3.11+ (the trial harness uses Python 3.13); no third-party
packages.
