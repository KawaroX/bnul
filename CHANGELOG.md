# Changelog

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
