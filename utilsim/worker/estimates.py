"""Initial estimates from measured runs, superseded by live checkpoint timing.

The reference is a completed Windows 10,000-home, 12-month offline test (2026-10-05),
not a speed guarantee. Local completed runs take precedence. Nothing is sent off-device.
"""
from __future__ import annotations

import calendar
import math
from datetime import date

REFERENCE = {'homes': 10000, 'months': 12, 'seconds': 171.734, 'fixedSeconds': 52.063}
ANALYSIS_REFERENCE = {'homes': 10000, 'months': 12, 'seconds': 62.031, 'fixedSeconds': 6.156}


def months_in(request):
    try:
        end = date.fromisoformat(request.get('asOf') or '')
        return end.month - 1 + end.day / calendar.monthrange(end.year, end.month)[1]
    except (ValueError, TypeError):
        return 12.0


def initial_estimate(recipe, history=()):
    homes, months = recipe['homes'], months_in(recipe.get('request', {}))
    samples = []
    for job in history:
        old = job.get('recipe', {})
        timing = (job.get('result') or {}).get('timings', {})
        stages = timing.get('stagesSeconds', {})
        # Baseline reuse skips generation; it cannot predict a fresh utility build.
        if (job.get('status') != 'complete' or not old.get('homes') or not timing.get('districtWallSeconds')
                or not any(k.startswith('generation.') for k in stages)
                or old.get('staffing') != recipe.get('staffing')):
            continue
        seconds = timing['districtWallSeconds'] + timing.get('finalizationSeconds', 0)
        fixed = sum(v for k, v in stages.items() if k.startswith(('generation.', 'baseline.', 'snapshot.', 'worker.')))
        samples.append({'homes': old['homes'], 'months': months_in(old.get('request', {})), 'seconds': seconds,
                        'fixedSeconds': min(fixed, seconds), 'chunk': old.get('chunkSize', 10000)})
    if samples:
        sample = min(samples, key=lambda s: abs(math.log(s['homes'] / homes))
                     + abs(math.log(s['chunk'] / recipe.get('chunkSize', 10000))))
        source, basis = 'history', 'Based on a completed run on this computer'
    else:
        sample = REFERENCE
        source, basis = 'benchmark', 'Based on the Windows reference test'
    seconds = (sample['fixedSeconds'] + (sample['seconds'] - sample['fixedSeconds']) * months / sample['months']) * homes / sample['homes']
    if not samples and recipe.get('staffing', '').startswith('shared'):
        seconds *= 2  # shared staffing has a probe pass before the final replay
    return {'estimatedTotalSeconds': round(seconds), 'etaSource': source,
            'etaBasis': f"{basis}: {sample['homes']:,} homes / {sample['months']:.1f} months.",
            'totalHomes': homes, 'months': round(months, 1)}


def progress_estimate(progress, initial):
    result = {**initial, **progress}
    if progress.get('status') == 'finalizing':
        return {**result, 'etaSeconds': None, 'etaBasis': 'Saving and checking the completed results.'}
    if progress.get('completed', 0) > 0 and (progress.get('etaSeconds') is not None or progress.get('etaSource') == 'live'):
        return {**result, 'etaSource': 'live', 'etaBasis': 'Updated from completed work in this run.'}
    remaining = initial['estimatedTotalSeconds'] * (1 - progress.get('completedHomes', 0) / initial['totalHomes']) - progress.get('activeSeconds', 0)
    return {**result, 'etaSeconds': round(remaining) if remaining > 0 else None, 'overrun': remaining <= 0,
            'etaSource': initial['etaSource'], 'etaBasis': initial['etaBasis']}


def analysis_estimate(recipe, key, samples):
    months = months_in(recipe.get('request', {}))
    matching = [s for s in samples if s['key'] == key and s['homes'] > 0 and s['months'] > 0]
    sample = matching[-1] if matching else ANALYSIS_REFERENCE
    fixed = sample.get('fixedSeconds', 0)
    seconds = (fixed + (sample['seconds'] - fixed) * months / sample['months']) * recipe['homes'] / sample['homes']
    return {'estimatedTotalSeconds': max(1, round(seconds)), 'totalHomes': recipe['homes'], 'months': round(months, 1),
            'etaSource': 'history' if matching else 'benchmark',
            'etaBasis': 'Based on the last comparable analysis on this computer.' if matching else
            'Based on measured replay and analysis time in the Windows reference test.'}
