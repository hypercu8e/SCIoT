"""Predeclared bounded search for an operational proxy-rate transition."""
INITIAL = (600, 800, 1000)
LOWER = (512, 400, 256, 128)
UPPER = (1500, 2000, 4000)


def choose_next(observations):
    """Map kbit/s -> strict 3-pair pass; return rate or a stopping reason."""
    for rate in INITIAL:
        if rate not in observations:
            return rate, 'initial grid'
    ordered = sorted(observations)
    if any(not observations[lo] and observations[hi] for lo in ordered for hi in ordered if lo < hi):
        return None, 'nonmonotonic outcomes: no single transition established'
    passed = [r for r in ordered if observations[r]]
    failed = [r for r in ordered if not observations[r]]
    if not passed:
        for rate in LOWER:
            if rate not in observations:
                return rate, 'seek a passing lower anchor'
        return None, 'no passing point down to 128 kbit/s'
    if not failed:
        for rate in UPPER:
            if rate not in observations:
                return rate, 'seek a failing upper anchor'
        return None, 'criterion still passes at 4000 kbit/s; no upper transition measured'
    lo, hi = max(passed), min(failed)
    if hi - lo <= 100:
        return None, f'observed transition bracket {lo}–{hi} kbit/s (not a confidence interval)'
    rate = int(((lo + hi) / 2) // 50 * 50)
    assert lo < rate < hi and rate not in observations
    return rate, 'refine observed bracket'
