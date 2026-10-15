# Changelog

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
