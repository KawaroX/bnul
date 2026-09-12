# Changelog

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
