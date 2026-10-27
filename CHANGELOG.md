# Changelog

## 0.6.0

- Automatic login no longer needs a browser: it runs the school CAS flow over plain HTTP (RSA-encrypted credentials, `secondAuth` check, form submit, ticket redirect, `auth/cas` exchange) and saves the token with its login-issued signing key. Over WebVPN the same flow goes through the rewritten WebVPN URLs with the scanned WebVPN cookies. A full expired-session recovery plus query takes about one second direct and 20-30 seconds over WebVPN.
- The HTTP login sends credentials only to `cas.bnu.edu.cn`, follows redirects only within the library and CAS hosts, and submits the password at most once per command. A captcha or second factor raises AUTH_INTERACTION_REQUIRED, a rejected password raises the new AUTH_REJECTED with the school's message, and an unexpected page raises AUTH_FLOW_CHANGED; none is retried. A stable private `device-id` next to the session stands in for the browser fingerprint.
- Playwright is now the optional `bnul[browser]` extra, needed only for `auth login` (visible window for a captcha or second factor). Without it that command fails with BROWSER_SUPPORT_MISSING and the install command.
- `auth setup` drops `--browser`; `auth login --browser` still saves the choice. `auth status` reports the automatic login method instead of the browser.
- watch treats AUTH_REJECTED, AUTH_FLOW_CHANGED and BROWSER_SUPPORT_MISSING as login failures and backs off.
- Document that an account has one active session: any new login (phone, web, another machine) invalidates the previous one.

## 0.5.5

- `book --seat` accepts a seat label such as `008`, resolved from the seat list the command already fetches; unknown or ambiguous labels fail with SEAT_NOT_FOUND and nothing is submitted.
- Booking validation no longer requests the unused seat timeline, saving one request per checked seat in `book` and `recommend`; `times` still shows it.
- `auth webvpn` waits for a just-started attempt's QR instead of returning `starting`, so agents need not poll `--status`.
- Rewrite the bundled skill around one command per task (no `--help` probe, no preview or `current` before authorized writes, rerun the original command after a WebVPN scan) and move WebVPN, login and watch details into on-demand references.
- Consolidate login commands under `auth`: `setup`, `login`, `status`, `logout`, `webvpn`, `install-browser`. Removed the top-level `login` alias, `auth import` and `auth exchange-link` (their tokens lack the login-issued signing key), and `auth clear`/`auth forget`, replaced by `auth logout`, which deletes the session, saved credentials, login browser profiles and WebVPN cookies.
- `auth setup`/`auth login --browser chromium|chrome|msedge` saves the browser for later automatic logins (`BNUL_BROWSER` still overrides).
- `auth status` reports the masked account, name and role, session save time, transport, credential source, browser and booking limits (max minutes, breach count, totals); contact details and the signing key are never shown. An expired or missing session returns `authenticated: false` with the reason and the next step instead of failing.
- `auth setup` falls back, only after an explicit confirmation, to a private 0600 `credentials.env` next to the session when the system keyring is unavailable. Automatic login reads it after environment variables; a later keyring setup or `auth logout` deletes it.
- `--json`, `--text`, `--no-proxy` and `--transport` are also accepted after the subcommand.
- `life` without an ID shows the current reservation's history; with no current reservation it fails with NO_CURRENT_RESERVATION.

## 0.5.4

- `cancel`/`stop --execute` no longer require `--expect-id`; when omitted, the current reservation read in the same command is the target. A supplied ID is still verified.
- `cancel`/`stop` follow the live status: RESERVE is cancelled and CHECK_IN/AWAY is stopped, whichever command was typed. A switch is reported in preview, text and JSON (`switched`, `requestedAction`, `action`, raw `result`); other states still fail with INVALID_RESERVATION_STATE.
- Add `-e` / `--exe` as aliases for `--execute` on `book`, `cancel`, `stop` and `watch`.

## 0.5.3

- Add fixed bN building aliases and building-scoped fN floor aliases, sharing a single directory request when resolving both. Require an explicit room outside the main library for seats/book.
- Extend fixed rN room aliases to all four known libraries. Show one canonical alias in CLI help, text catalogs and skill tables while preserving older selector syntax and JSON fields for compatibility.
- Prefer aliases with ID discovery as a fallback, clarify the default main-library 3F study room for seats/book, and remove redundant current/catalog/booking-preview calls from the agent skill.

## 0.5.2

- Parse the school's real `awayTime` representation as seconds since Beijing midnight; cross-check `awayTimeM` and `awayRange` when present. Retain explicit timestamp support and fail closed on conflicting fields.
- Keep observing reservations that naturally finish before the away deadline; do not stop or rebook them or report a deadline parsing failure.
- Classify deadline/rule, authentication, query, missed-window and heartbeat alerts separately. Only authentication-related failures mention login backoff.
- Persist minimal, bounded reservation diagnostics without account credentials; expose the last observation in status. Scheduled sleep no longer masks an unresolved business failure as healthy.
- Add anonymized real-response regression fixtures, including the 2026-10-17 incident, and replay tests that perform no school mutations.

## 0.5.1

- Run reservation checks only from 08:00 to 23:00 Asia/Shanghai; sleep overnight without starting queries, login recovery or alerts, including pending Slack deliveries and independent health alarms.
- Poll idle accounts every 30 minutes, active use every 20 minutes, and away reservations every 7 minutes when over 10 minutes remain or every 2 minutes otherwise. Keep unsigned reservations and errors at 2 minutes.
- Separate local process heartbeats from reservation queries, preserving watchdog/hang detection during long polling intervals; report sleep state, next check time and last actual query separately.
- Guard new requests at closing time, wake at 08:00, and retain existing action journals, credentials, notification receipts and authentication backoff across upgrades.

## 0.5.0

- Add opt-in reservation monitoring: check every 120 seconds and handle unsigned/away reservations only when less than five minutes remain; preserve seat and original end time.
- Keep the 0.4.1 signing-key and direct/WebVPN fixes; recover sessions using existing credentials, persist login backoff, and continue observing instead of exiting silently on authentication failures.
- Add durable Slack failure/recovery/action notifications with delivery receipts, retry/backoff and deduplication.
- Journal mutations before submission and reconcile interrupted requests without replay; enforce cancellation limits, state rechecks and captcha preflight.
- Ship systemd monitor/watchdog and independent heartbeat timer, local status inspection, deployment and acceptance instructions.

## 0.4.1

- Fix queries failing when the public configuration returns an empty `hmacKey`: capture the signing key from the successful login response, decrypt it with the existing algorithm, and persist it with its matching token.
- Recover legacy sessions that lack a signing key once; preserve explicit-token behavior and keep `auth status` read-only without automatic login.
- Preserve direct/WebVPN support and compatibility with servers that still supply the key in public configuration.
- Clarify single-command agent invocation and error handling in the bundled skill; add signing-session regression tests.

## 0.4.0

- Add per-client direct, school WebVPN and pre-request auto transport selection; preserve no-replay guarantees for writes.
- Add official phone QR login, detached polling, status checks and QR refresh; return native media paths outside credential directories.
- Support school CAS recovery through authenticated WebVPN and an explicitly configured Chrome executable.
- Add opt-in Linux OpenConnect/systemd deployment with account-password reconnect and routes restricted to library and CAS hosts.
- Update the bundled bnu-library skill to show the QR image in the current chat and resume verified queries after authentication.

## 0.3.4

- Add task-oriented default text output; JSON mode preserves all fields without display-layer truncation.
- Retry transient network errors once on read-only requests.
- Defensive parsing for rooms pagination when the server returns unexpected totalPage values.

## 0.3.3

- Add -v / --version to print the installed package version without login or network access.

## 0.3.2

- Add cancel previews and guarded submission for unsigned current reservations; distinguish cancel from stop by reservation status.
- Add paginated history and breach queries.
- Document cancellation, uncertain-write reconciliation and rebooking in README and skill.

## 0.3.1

- Replace machine-local room numbering with shared fixed main-library numbers 1–9, documented in README and skill.
- Ignore legacy numbering caches; unknown rooms remain selectable by name or ID without automatic numbering.
- Preserve fixed numbers across server reordering, missing rooms and floor filters.

## 0.3.0

- Add room-list and bare rooms catalog commands with persistent building-scoped numbers, aliases, short names and IDs.
- Allow room IDs, numbers, names and unambiguous fragments in seats/book/recommend.
- Add strict preferred room order and compact digit sequences (0 = 10); default recommendation becomes 5 candidates / 50 checks without a hardcoded personal room preference.
- Update skill room-choice and now semantics, preserving complete-interval validation.

## 0.2.0

- Add read-only `recommend` for exact study intervals, including `now`; verify each candidate against server start/end options.
- Search across rooms with explicit building/floor/room scope, bounded checks, and partial-search reporting.
- Teach the skill to interpret study plans, present candidates and reasons, and reserve only within user authorization.

## 0.1.0

- Initial CLI release: resources, seats, time options, booking previews and submission, current/recent reservations, lifecycle, stop.
- Immediate bookings: `--start now`, `--start 现在`, or `--start=-1`; availability queries resolve the current minute, booking submission sends -1. Fixed times must match server options.
- Background authentication recovery, system credential storage across macOS/Windows/Linux, and environment credentials for headless deployments.
- Install with uv/pipx from GitHub; `bnul auth install-browser` and `bnul skill install` bootstrap browser and agent skill.
- Tests cover protocol, authentication, packaging helpers, and immediate bookings. Windows/Linux branches are mocked pending native CI verification; live booking mutations were not exercised.
