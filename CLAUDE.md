# utilsim: notes for Claude

## Cost guardrails (CI, deploys, cloud)

Every paid or metered resource has a budget: GitHub Actions minutes, Vercel builds and deployments, cloud credits.
On October 4, 2026, CI used the GitHub Free plan's 2,000 monthly Actions minutes in four days: every push ran the
full suite twice (once for the branch push, once for the pull request), at about 11 billed minutes each. Avoid that
kind of easy overrun:

- **Test locally first, push once.** Run the checks below before pushing; batch commits and push when they pass. A
  push is not a way to run the tests.
- **CI runs on pull requests only** (and by hand, `workflow_dispatch`), never on every branch push. A new push
  cancels the PR's run still going. A draft PR runs nothing: keep a PR in draft while iterating on it and mark it
  ready when CI should run. Markdown and `docs/` changes alone run nothing; viewer-only changes skip the engine suite.
- **Re-run a failed job at most once**, and only when it died before any test ran. A job that fails in seconds with
  no logs is usually billing: read the job's annotations ("recent account payments have failed or your spending
  limit needs to be increased") before anything else, and tell the user.
- **Before adding a workflow, job, matrix entry or schedule**, estimate its minutes a month and say so. Every job gets
  `timeout-minutes`; no cron schedules without the user's yes. GitHub rounds each job up to a whole minute, so prefer
  one job with steps over many short jobs.
- **Expensive work runs once.** Cache what can be cached; reuse results instead of recomputing them in a loop.

The repository is public for now (GitHub-hosted runners are free for public repositories). If it goes private again,
a CI run costs about 5 billed minutes with the engine suite and 1 without.

## Checks before pushing

```bash
uv run ruff check .
uv run pytest -m "not slow" -n auto        # parallel (pytest-xdist); drop -n auto to debug one test
(cd packages/town-viewer && npm test)
node scripts/viewer_conformance.mjs examples/village-480-seed42
```

Run only what the change touches while iterating (`uv run pytest tests/test_m2c_chain.py -n auto`), and the full set
once before the push.
