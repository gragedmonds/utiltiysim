# utilsim: notes for Claude

## Supported UI target

Utility Studio is a downloadable offline desktop application. Prioritise the desktop
browser opened by the launcher, with keyboard and mouse interaction. Phone and tablet
support is deprecated: do not add dedicated mobile navigation, touch-only features,
mobile-specific layouts or routine mobile viewport checks unless the user requests them.

Keep layouts usable when a desktop window is resized, used side by side, or viewed with
Windows display scaling or browser zoom. Responsive CSS that serves those desktop needs
is still useful; do not remove all media queries indiscriminately. Retire dedicated mobile
behaviour when working on the relevant screen. Verify at ordinary desktop sizes and, when
the layout changes, a smaller desktop window or increased zoom.

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
a CI run costs about 9 billed minutes with the engine suite and 1 without, and an app build (four operating
systems: about 2 minutes on Linux, 3 on Windows billed 2x, 2 and 7 on the two macOS runners billed 10x) about 100.

## Checks before pushing

```bash
uv run ruff check .
uv run pytest -m "not slow" -n auto        # parallel (pytest-xdist); drop -n auto to debug one test
(cd packages/town-viewer && npm test)
node scripts/viewer_conformance.mjs examples/village-480-seed42
```

Run only what the change touches while iterating (`uv run pytest tests/test_m2c_chain.py -n auto`), and the full set
once before the push.
