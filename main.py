"""Forecast GTA VI's launch-day Twitch viewers, hour by hour (hours 2..24).

Method: comparable-launch log-ratio regression. Every comparable in the case
file is a past big game launch with hourly Twitch viewers from 14 days before
its release day to 3 days after it. For each comparable we take its release
day's 24 hourly counts and express hours 2..24 as log ratios to its own hour-1
count: r_h = ln(viewers_h / viewers_1). The shape of a launch day is driven
mostly by when the game unlocked around the world and how big the launch is,
so two things matter:

1. Which comparables to trust. The unlock notes name a tier and a pattern.
   Early-access launches (their hour 1 is already day 4 of play), weak
   analogues (free-to-play, slow-burn) and simultaneous global unlocks (their
   hour 1 is nearly empty, so their ratios explode) are left out. Rolling
   midnight-local launches -- the pattern GTA VI itself follows -- count
   extra. A comparable with no usable hour-1 count (the target's own
   pre-release history is one) is skipped.

2. Scale. Across clean rolling launches, the log ratio of every later hour
   falls almost linearly with the log of the hour-1 count (a launch whose
   first hour already drew 800k cannot triple by the evening; one whose first
   hour drew 25k usually does). So for each hour we fit a weighted least
   squares line of r_h on ln(hour-1 count) over the trusted comparables and
   read it at the target case's own ln(hour-1 print). The prediction is
   clamped to the range of ratios the comparables actually showed that hour,
   so an extreme hour-1 print can never extrapolate the forecast off a cliff.

The five quantiles of each hour are the fitted value plus normal-quantile
offsets times the residual spread of that hour's fit, widened a little when
the target's hour-1 count sits far from the comparables' (leverage), and
scaled by 0.65 -- the factor that scored best on the practice cases and on
leave-one-out runs over the comparables. When too few comparables survive
the filter, the fit falls back to every comparable with an hour 1, then to
the median ratio curve, then to a persistence forecast, so the program always
emits a valid forecast and never crashes.

Standard library only, no network, no randomness: the same input bytes always
produce the same output bytes. Reads every *.in file in $MAKEFUN_INPUT_DIR
(else /input/) in name order and writes one <id>.out per case to
$MAKEFUN_OUTPUT_DIR (else /output/).
"""

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# Standard normal quantiles at LEVELS.
Z = [-1.6448536269514722, -0.6744897501960817, 0.0,
     0.6744897501960817, 1.6448536269514722]

SPREAD_MULT = 0.65      # residual-spread calibration (practice + leave-one-out)
MIN_FIT = 4             # comparables needed for the regression fit
SIGMA_FLOOR = 0.05      # never narrower than this, in log units
SIGMA_CAP = 1.2         # never wider than this, in log units
FALLBACK_SIGMA = 0.30   # spread used when an hour has too few fitted points
PERSIST_SIGMA = 0.15    # spread of the last-resort persistence forecast
MAX_VIEWERS = 1e9
RATIO_FLOOR = math.log(0.02)  # sanity guard: no hour below 2% of hour 1
RATIO_CEILING = math.log(50.0)  # sanity guard: no hour above 50x hour 1


def parse_time(text):
    """ISO 8601 -> aware datetime, or None when unparseable."""
    if not isinstance(text, str):
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def norm_ppf(p):
    """Inverse standard normal CDF (Acklam's rational approximation)."""
    if p <= 0.0:
        return -8.0
    if p >= 1.0:
        return 8.0
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285984469534e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1.0 - 0.02425
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    if p > phigh:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
        (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)


def z_scores(levels):
    """Normal quantiles for the requested levels (exact table when standard)."""
    if list(levels) == LEVELS:
        return list(Z)
    return [norm_ppf(float(t)) for t in levels]


def comparable_weight(comp):
    """Trust weight from the unlock note: 0 = leave out, 1 = use, 1.5 = prefer.

    Early-access-contaminated launches, weak analogues and the target's own
    pre-release history carry no usable launch-day shape. Simultaneous global
    unlocks have a near-empty hour 1, so their ratios are meaningless for a
    rolling-midnight target. Rolling midnight-local launches match GTA VI's
    own pattern and count extra.
    """
    note = str(comp.get("unlock") or "").lower()
    if "early-access-contaminated" in note or "early-access contaminated" in note:
        return 0.0
    if "tier: weak" in note:
        return 0.0
    if "target-his" in note or "not a launch" in note:
        return 0.0
    simultaneous = ("single global" in note or "simultaneous" in note
                    or "single time" in note)
    rolling = ("midnight local" in note or "rolling" in note)
    if simultaneous and not rolling:
        return 0.0
    if rolling:
        return 1.5
    return 1.0


def release_day_series(comp):
    """{hour: viewers} for the 24 hours of the comparable's release day."""
    day_start = parse_time(comp.get("day_start"))
    if day_start is None:
        return {}
    series = {}
    hourly = comp.get("hourly") or []
    for point in hourly:
        if not isinstance(point, dict):
            continue
        at = parse_time(point.get("from"))
        viewers = point.get("viewers")
        if at is None or viewers is None:
            continue
        try:
            viewers = float(viewers)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(viewers):
            continue
        hour = int((at - day_start).total_seconds() // 3600) + 1
        if 1 <= hour <= 24:
            series[hour] = viewers
    return series


def ratio_curves(case):
    """Usable comparables as (weight, hour-1 count, {hour: log ratio}).

    Sorted by comparable name so the fit sums in a fixed order and two runs
    produce identical bytes.
    """
    curves = []
    comps = case.get("comparables") or []
    if not isinstance(comps, list):
        return curves
    for comp in sorted((c for c in comps if isinstance(c, dict)),
                       key=lambda c: str(c.get("name") or "")):
        series = release_day_series(comp)
        first = series.get(1)
        if first is None or first <= 0:
            continue
        ratios = {}
        for hour in range(2, 25):
            value = series.get(hour)
            if value is not None and value > 0:
                ratios[hour] = math.log(value / first)
        if ratios:
            curves.append((comparable_weight(comp), first, ratios))
    return curves


def hour1_print(case):
    """The target case's hour-1 print, with defensive fallbacks."""
    known = case.get("known") or []
    if isinstance(known, list):
        for row in known:
            if isinstance(row, dict) and row.get("hour") == 1:
                try:
                    value = float(row.get("viewers"))
                except (TypeError, ValueError):
                    continue
                if math.isfinite(value) and value > 0:
                    return value
    hourly = case.get("history_hourly") or []
    if isinstance(hourly, list) and hourly:
        for row in reversed(hourly):
            if isinstance(row, dict):
                try:
                    value = float(row.get("viewers"))
                except (TypeError, ValueError):
                    continue
                if math.isfinite(value) and value > 0:
                    return value
    return 1.0


def forecast_hours(case):
    """The hours to forecast: the case's list when usable, else 2..24."""
    rows = case.get("forecast") or []
    hours = []
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("hour"), int):
                if 2 <= row["hour"] <= 24:
                    hours.append(row["hour"])
    if sorted(set(hours)) != list(range(2, 25)):
        return list(range(2, 25))
    return sorted(set(hours))


def weighted_median(pairs):
    """Median of (value, weight) pairs by cumulative weight."""
    ordered = sorted(pairs)
    total = sum(w for _, w in ordered)
    if total <= 0:
        return ordered[len(ordered) // 2][0]
    target = 0.5 * total
    seen = 0.0
    for value, weight in ordered:
        seen += weight
        if seen >= target:
            return value
    return ordered[-1][0]


def fit_hour(points, log_p1):
    """Weighted least squares of log ratio on log hour-1 for one hour.

    points: [(log hour-1, log ratio, weight)]. Returns (prediction, sigma).
    The prediction is clamped to the observed ratio range; sigma is the
    residual spread widened by the prediction's leverage.
    """
    total_w = sum(w for _, _, w in points)
    xbar = sum(w * x for x, _, w in points) / total_w
    ybar = sum(w * y for _, y, w in points) / total_w
    sxx = sum(w * (x - xbar) ** 2 for x, _, w in points)
    slope = 0.0
    if sxx > 0:
        slope = sum(w * (x - xbar) * (y - ybar) for x, y, w in points) / sxx
    pred = ybar + slope * (log_p1 - xbar)
    lo = min(y for _, y, _ in points)
    hi = max(y for _, y, _ in points)
    pred = max(lo, min(hi, pred))
    # Absolute sanity guardrails: they never bind for a realistic hour-1
    # print, but they keep a degenerate input from extrapolating wildly.
    pred = max(RATIO_FLOOR, min(RATIO_CEILING, pred))
    var = sum(w * (y - (ybar + slope * (x - xbar))) ** 2
              for x, y, w in points) / total_w
    sigma = max(SIGMA_FLOOR, math.sqrt(var))
    leverage = 1.0 + 1.0 / len(points)
    if sxx > 0:
        leverage += (log_p1 - xbar) ** 2 / sxx
    sigma = min(SIGMA_CAP, sigma * math.sqrt(leverage) * SPREAD_MULT)
    return pred, sigma


def guard_row(quantiles):
    """Finite, > 0, <= 1e9, non-decreasing."""
    out = []
    prev = 0.0
    for q in quantiles:
        if q is None or not math.isfinite(q):
            q = prev if prev > 0 else 1.0
        q = max(1.0, min(MAX_VIEWERS, float(q)))
        q = max(q, prev)
        out.append(q)
        prev = q
    return out


def forecast_case(case):
    """One forecast dict for one case dict. Never raises for bad shapes."""
    levels = case.get("levels") or LEVELS
    try:
        levels = [float(t) for t in levels]
        if len(levels) != 5 or not all(0.0 < t < 1.0 for t in levels):
            levels = list(LEVELS)
    except (TypeError, ValueError):
        levels = list(LEVELS)
    zs = z_scores(levels)
    hours = forecast_hours(case)
    p1 = max(1.0, hour1_print(case))
    log_p1 = math.log(p1)

    curves = ratio_curves(case)
    trusted = [(w, h1, r) for (w, h1, r) in curves if w > 0]
    if len(trusted) >= MIN_FIT:
        pool = trusted
    elif len(curves) >= MIN_FIT:
        pool = [(1.0, h1, r) for (_, h1, r) in curves]
    else:
        pool = []

    rows = []
    for hour in hours:
        if pool:
            points = [(math.log(h1), ratios[hour], w)
                      for (w, h1, ratios) in pool if hour in ratios]
        else:
            points = []
        if len(points) >= MIN_FIT:
            pred, sigma = fit_hour(points, log_p1)
            quantiles = [p1 * math.exp(pred + z * sigma) for z in zs]
        elif curves:
            # Too few points for a fit this hour: median ratio, fixed spread.
            pairs = [(ratios[hour], w if w > 0 else 1.0)
                     for (w, _, ratios) in curves if hour in ratios]
            if pairs:
                med = weighted_median(pairs)
                quantiles = [p1 * math.exp(med + z * FALLBACK_SIGMA) for z in zs]
            else:
                quantiles = [p1 * math.exp(z * PERSIST_SIGMA * math.sqrt(hour - 1))
                             for z in zs]
        else:
            # No comparables at all: persistence with a widening spread.
            quantiles = [p1 * math.exp(z * PERSIST_SIGMA * math.sqrt(hour - 1))
                         for z in zs]
        rows.append({"hour": hour, "q": guard_row(quantiles)})
    return {"hours": rows}


def persistence_forecast(case):
    """Last-resort forecast from the hour-1 print alone. Never raises."""
    try:
        p1 = max(1.0, hour1_print(case))
    except Exception:
        p1 = 1.0
    rows = []
    for hour in range(2, 25):
        spread = PERSIST_SIGMA * math.sqrt(hour - 1)
        rows.append({"hour": hour,
                     "q": guard_row([p1 * math.exp(z * spread) for z in Z])})
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = None
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(case, dict):
                raise ValueError("case is not a JSON object")
            forecast = forecast_case(case)
        except Exception:
            try:
                forecast = persistence_forecast(case or {})
            except Exception:
                forecast = persistence_forecast({})
        out = json.dumps(forecast, separators=(",", ":")) + "\n"
        (OUTPUT_DIR / f"{path.stem}.out").write_text(out, encoding="utf-8")


if __name__ == "__main__":
    main()
