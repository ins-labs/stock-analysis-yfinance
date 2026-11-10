# Public stock-analysis runner

The enabled command is `python fixture_demo.py`. It uses invented data and makes no Yahoo request. It proves the runner plumbing only, not real stock analysis. The dispatcher rejects every analysis.py command, even if the repository variable changes.

## Manual synthetic run

1. Set the persistent repository Actions variable `ANALYSIS_COMMAND` to `python fixture_demo.py`.
2. Open Actions > Public stock analysis > Run workflow and select an accepted branch.
3. Check the original job conclusion and labeled synthetic output. Pull requests to main run the deterministic tests automatically, but do not execute the persistent command. There are no automatic push or scheduled runs, dispatch-input overrides, uploaded artifacts or raw market-data exports.

Commands and synthetic results appear in public job logs. Do not supply credentials, private holdings or other private inputs. The fixture and demo code are CC0-1.0 and print `SYNTHETIC_FIXTURE_ONLY` with `real_market_data:false`.

## Held real-data candidate

This candidate adds admission checks in analysis.py and 17 invented-data test methods. Together with the seven existing methods, all 24 methods are UNRUN against this candidate. A prior synthetic run does not qualify these changed bytes. Source checks are not runtime proof or permission to enable real data. Normal issue-first branches, local Git, independent review, qualified host tests and protected-main gates still apply before publication or use of a changed version.

The analysis.py path remains disabled by the dispatcher. Its held interface accepts 1-10 distinct ticker symbols and periods 1mo, 3mo, 6mo, 1y, 2y or 5y. POUL.CA is only a context-based demonstration candidate, not a selected trade or verified provider symbol.

### Admission policy

- Every Close value must be numeric, finite and strictly positive. Missing or invalid interior rows fail; they are not dropped. Boolean and text values are not coerced into prices.
- Require at least two observations on distinct daily dates, in an actual DatetimeIndex with no missing timestamps, duplicate timestamps or reversed/out-of-order dates. Multiple observations on the same calendar date fail. This is a daily-history policy, not intraday support.
- Requested identity and provider-returned history metadata identity are separate. The provider symbol must exactly equal the requested symbol. Missing, blank, whitespace-padded or mismatched identities fail. No alias substitution or request-based identity fallback is allowed. Results name requested_ticker and provider_ticker separately.
- Currency must be a nonempty provider string label, not a missing/null/blank/UNKNOWN placeholder. This does not validate an ISO currency code or prove the label is correct.
- Provider timezone must be nonempty and recognized by ZoneInfo. An aware index must name exactly the same zone as the provider metadata. Equivalent aliases with different names are refused rather than silently normalized. Naive indexes are accepted as calendar-date labels with a separately required provider timezone, not as localized or verified instants.
- Adjusted price change must be finite. Dividend events and their sum must be finite numbers; missing dividend events retain zero-fill behavior. Invalid admission produces a failure and no successful price summary for that ticker.

`auto_adjust=True` is explicit. Output is adjusted price change between the first and last admitted Close values, not total return, a trade recommendation or a guaranteed investment return. Dividend output is the sum of events in the returned historical window. Provider data may be missing, delayed or revised.

The new fixtures use invented frames and a fake yfinance module for integration wiring. They make no provider requests. Actual availability and meaning of symbol, currency and timezone fields in the pinned provider remain unverified. Absent provider symbol metadata must fail, not be filled from the request. There is no live symbol, market-data or provider-compatibility result for this candidate.

## Data-access and output rights remain on hold

No permission has been established for automated Yahoo historical-data access or public derived-metric output. The yfinance code license is not a market-data acquisition or redistribution grant. Keeping raw rows out of logs does not establish permission for derived metrics. Validator changes do not supply a rights grant or authorize a live request. Do not enable or dispatch the real-data path until access and output rights are resolved separately and the changed candidate passes its normal review and test gates.

Relevant sources for that unresolved review:
- https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html
- https://legal.yahoo.com/us/en/yahoo/terms/product-atos/apiforydn/index.html
- https://legal.yahoo.com/us/en/yahoo/terms/product-atos/finance/index.html
- https://github.com/ranaroussi/yfinance
- https://raw.githubusercontent.com/ranaroussi/yfinance/e2f6104164b70085556fe2f8e194cf3ca18550f5/LICENSE.txt
- https://raw.githubusercontent.com/ranaroussi/yfinance/e2f6104164b70085556fe2f8e194cf3ca18550f5/yfinance/scrapers/history.py

## Pull-request test gate

Pull requests to main run the same `analyze` job on `opened`, `synchronize` and `reopened` events. The job installs the pinned dependencies and runs `python -m unittest discover -s tests -v`. It does not execute the persistent repository command on these events. That command, and its `ANALYSIS_COMMAND` binding, are present only in the manual `workflow_dispatch` step. These changed workflow bytes are UNRUN; the earlier manual 24-test result does not qualify this event path.

The pull-request job has contents-read permission only. Checkout does not persist credentials. No repository secrets, write token, environments, caches, artifacts or self-hosted runner are used. The event is `pull_request`, never `pull_request_target`. Pull-request source is untrusted code executed for tests on a standard hosted runner, not privileged code. It is not a general provider-network sandbox: future changed tests or dependencies could make requests, so the reviewed fake-provider-only tests and the no-real-data policy still matter. No guarantee of network isolation is made.

## Execution boundaries

Python 3.12.16 and yfinance1.8.0 remain pinned; transitive dependencies are not fully hash-locked. Checkout and setup-python use pinned commits. Checkout does not persist credentials, and GITHUB_TOKEN has contents-read only. The workflow uses a standard ubuntu-24.04 GitHub-hosted runner, no larger runner, cache or uploaded artifacts. No test/CI timeout is authored. No unlimited capacity or future billing guarantee is implied.

The only enabled dispatcher argv is the fixed Python fixture entry, parsed without a shell. This is not an arbitrary shell-command service. Repository writers can change source, but any such change requires fresh review and test gates; changing the persistent command alone cannot enable real-market analysis.
