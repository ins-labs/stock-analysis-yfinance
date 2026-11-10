# PUBLICATION HOLD: source-only draft

Do not dispatch the Yahoo command until provider/API/output terms are resolved. Public derived summary metrics are NOT assumed licensed. The fixture-only dispatcher mechanically rejects the real-market command. The separate synthetic command below proves plumbing only and does not complete real stock analysis.

# Public yfinance analysis runner

Draft source, not yet published, reviewed, tested or demonstrated.

One public repository for yfinance analysis. A persistent repository Actions variable holds the command. A manual workflow trigger runs it. Commands and historical market-data results are public. There are no credentials, private holdings, trading or automatic schedules.

## Configure and run

After normal issue-first branch, independent review, public CI and main-merge gates:

1. In repository Settings > Secrets and variables > Actions > Variables, create or update `ANALYSIS_COMMAND`.
2. Set the exact command `python fixture_demo.py`. Any analysis.py command is now rejected by the dispatcher, even if the repository variable is changed.
3. Open Actions > Public stock analysis > Run workflow, select the accepted branch, then run manually. No dispatch inputs override the persistent variable.
4. Inspect the original job conclusion and analysis output, not merely package installation. Derived JSON summaries are in the public job log. No raw historical rows/CSV are printed. This reduction does not establish provider permission. Empty/invalid/unavailable data makes the process fail, not an empty success.

POUL.CA is a context-based demonstration candidate, not a user-selected trade or verified Yahoo symbol/data claim. The first run must check that actual returned symbol, dates, currency and rows fit the intended demonstration. Missing or unexpected data stays a failure to report, not a reason to silently substitute another ticker.

Supported periods: 1mo, 3mo, 6mo, 1y, 2y, 5y. Up to ten distinct ticker symbols. The command is parsed into a fixed Python argv, never shell-evaluated. Unknown commands/flags, paths and shell fragments are rejected. Those are the held analysis.py source contract, not enabled dispatcher choices. The only enabled dispatcher command is python fixture_demo.py; it is not a general arbitrary shell runner.

`auto_adjust=True` is explicit. Reported change is adjusted price change between the first and last returned Close values, not a guaranteed investment return. Dividend events come from that same returned historical window. Currency and exchange timezone are reported when available; UNKNOWN is not inferred EGP. Yahoo data may be delayed, missing or revised and is not investment advice.

## Source and execution

- Python 3.12.16, yfinance1.8.0 pinned. Transitive dependencies are not fully hash-locked in this draft.
- checkout/setup-python are pinned to exact observed upstream tag commits. Checkout does not persist credentials. GITHUB_TOKEN has contents-read only.
- Only workflow_dispatch triggers execution. No automatic market requests on push, pull_request or schedules. Seven deterministic tests are authored UNRUN; no TDD RED/PASS is claimed. Later approved CI must run them before analysis.
- Standard ubuntu-24.04 GitHub-hosted runner in a public repository is within GitHub's documented free runner scope. No larger runner, cache or uploaded artifacts. Job-log output avoids artifact-storage commitments; no claim of unlimited platform capacity.
- No authored test/CI timeout. No new auth keys, token scopes, settings, account changes or public repo creation from this draft.

## Evidence still needed before a working-run claim


## Upstream sources

- https://github.com/ranaroussi/yfinance
- https://raw.githubusercontent.com/ranaroussi/yfinance/e2f6104164b70085556fe2f8e194cf3ca18550f5/LICENSE.txt (Apache2.0 upstream code license; market-data usage terms remain separate)
- https://raw.githubusercontent.com/ranaroussi/yfinance/e2f6104164b70085556fe2f8e194cf3ca18550f5/yfinance/scrapers/history.py
- https://docs.github.com/en/billing/managing-billing-for-your-products/managing-billing-for-github-actions/about-billing-for-github-actions
- https://docs.github.com/en/rest/interactions/repos
- https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps

## Data-rights and synthetic alternative

Yahoo Terms of Service section3(b)(ix) restricts automated data collection without express prior permission. Section3(h) restricts reproduction/distribution/derivative works without written permission (the exact scope and applicability need review). Developer API terms allow use subject to API documents and reserve output rights; no explicit public-derived-metrics exemption was established. The Finance Community terms are about community posts, not a general historical-price API redistribution grant. Removing raw CSV is a sensible minimum-output design, not a legal permission claim.

A distinctly labeled plumbing command is `python fixture_demo.py`. It makes NO Yahoo request, uses invented prices with no real ticker/date/currency, prints SYNTHETIC_FIXTURE_ONLY in each result, and proves only persistent variable -> manual dispatch -> child result/exit. The invented fixture and demo code in that file are CC0-1.0. It cannot be reported as POUL.CA or real-market-data success.

Additional terms inspected:
- https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html
- https://legal.yahoo.com/us/en/yahoo/terms/product-atos/apiforydn/index.html
- https://legal.yahoo.com/us/en/yahoo/terms/product-atos/finance/index.html
- https://raw.githubusercontent.com/actions/python-versions/main/versions-manifest.json (3.12.16 Linux24.04 build listed)

## R2 review findings retained for future real-market enablement

Source review accepted the synthetic-only boundary, not real Yahoo use. Unchanged analysis.py remains unsuitable for real-data admission until ALL close values are finite/positive; the index is demonstrably dated, unique and chronological with enough distinct dates; requested and returned provider ticker identity are separate and verified or rejected; missing/null/empty currency/timezone become UNKNOWN; corresponding source fixtures cover failures, including intermediate invalid values. Current seven tests remain UNRUN and do not prove these requirements. No provider rights have been inferred. The R2 dispatcher prevents variable-only enablement of that path, but a repository writer can always change source and would need a fresh accepted change.
