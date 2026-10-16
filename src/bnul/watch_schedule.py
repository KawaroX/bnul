"""Beijing daytime policy, shared by the monitor and its independent health check."""
from datetime import timedelta
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo('Asia/Shanghai')
HEARTBEAT_SECONDS = 60


def active(now):
    return 8 <= now.astimezone(SHANGHAI).hour < 23


def next_open(now):
    local = now.astimezone(SHANGHAI)
    opening = local.replace(hour=8, minute=0, second=0, microsecond=0)
    return opening if local < opening else opening + timedelta(days=1)


def sleeping(now):
    return {'event': 'sleeping', 'nextCheckAt': next_open(now).isoformat()}


def interval_for(result, urgent=120):
    if result['event'] == 'idle':
        return 1800
    if result['event'] == 'observing':
        if result.get('status') == 'CHECK_IN':
            return 1200
        if result.get('status') == 'AWAY' and result.get('remainingSeconds', 0) > 600:
            return 420
    # Unsigned bookings, unknown states, failures and action reconciliation stay prompt.
    return urgent


def schedule_for(result, started, finished, urgent=120):
    if not active(finished):
        return {'mode': 'sleeping', 'nextCheckAt': next_open(finished).isoformat(), 'intervalSeconds': None}
    interval = interval_for(result, urgent)
    close = finished.astimezone(SHANGHAI).replace(hour=23, minute=0, second=0, microsecond=0)
    due = min(max(started + timedelta(seconds=interval), finished), close)
    return {'mode': 'waiting', 'nextCheckAt': due.isoformat(), 'intervalSeconds': interval}
