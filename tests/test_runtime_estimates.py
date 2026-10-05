from utilsim.worker.estimates import analysis_estimate, initial_estimate, months_in, progress_estimate


def recipe(homes=50000, as_of='2026-12-31'):
    return {'homes': homes, 'chunkSize': 10000, 'staffing': 'independent-districts', 'request': {'asOf': as_of}}


def test_reference_estimate_is_available_before_any_checkpoint_and_scales_months():
    initial = initial_estimate(recipe())
    assert initial['estimatedTotalSeconds'] == 859
    assert initial['etaSource'] == 'benchmark'
    assert progress_estimate({}, initial)['etaSeconds'] == 859
    # Shortening the year does not eliminate the cost of building the town.
    half = initial_estimate(recipe(as_of='2026-06-30'))['estimatedTotalSeconds']
    assert 859 / 2 < half < 859
    assert months_in({'asOf': '2028-02-29'}) == 2


def test_local_measurements_win_then_live_progress_replaces_the_initial_estimate():
    history = [{'status': 'complete', 'recipe': recipe(25000), 'result': {'timings': {
        'districtWallSeconds': 430, 'finalizationSeconds': 10, 'stagesSeconds': {'generation.roads': 100}}}}]
    initial = initial_estimate(recipe(), history)
    assert initial['etaSource'] == 'history'
    assert initial['estimatedTotalSeconds'] == 880
    assert progress_estimate({'activeSeconds': 80}, initial)['etaSeconds'] == 800
    live = progress_estimate({'completed': 1, 'etaSeconds': 555}, initial)
    assert live['etaSource'] == 'live' and live['etaSeconds'] == 555
    assert progress_estimate({'activeSeconds': 900}, initial)['etaSeconds'] is None
    assert progress_estimate({'status': 'finalizing'}, initial)['etaSeconds'] is None


def test_failed_or_reused_builds_do_not_teach_fresh_build_speed_and_analysis_stays_separate():
    history = [{'status': 'complete', 'recipe': recipe(), 'result': {'timings': {
        'districtWallSeconds': 10, 'stagesSeconds': {'baseline.verify_reuse': 5}}}}]
    assert initial_estimate(recipe(), history)['etaSource'] == 'benchmark'
    sample = {'key': 'table', 'homes': 10000, 'months': 12, 'seconds': 20}
    assert analysis_estimate(recipe(), 'table', [sample])['estimatedTotalSeconds'] == 100
    assert analysis_estimate(recipe(), 'trend', [sample])['etaSource'] == 'benchmark'
