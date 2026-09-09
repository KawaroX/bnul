"""Read-only, bounded search for seats covering the exact requested interval."""
from datetime import datetime
from zoneinfo import ZoneInfo
from .client import BUILDING, ROOM, Error, day, identifier, query_start


def recommend(client, date, start, end, building=BUILDING, room=None, floor='0',
              limit=3, max_checks=30):
    date = day(date)
    if not 1 <= limit <= 20 or not limit <= max_checks <= 200:
        raise Error('limit 需为 1–20，max-checks 需不小于 limit 且不超过 200')
    now = datetime.now(ZoneInfo('Asia/Shanghai'))
    if date < str(now.date()) or (date == str(now.date()) and start != -1 and start < now.hour * 60 + now.minute):
        raise Error('计划开始时间已过去；从现在开始请用 --start now')
    if not 0 <= query_start(start, date) < end < 1440:
        raise Error('结束时间必须晚于开始时间，且不可跨天')
    rooms = client.rooms(building, date, start, end, floor=floor)
    if room:
        rooms = [r for r in rooms if str(r['id']) == identifier(room)]
        if not rooms:
            raise Error('在指定楼馆/楼层查询结果中找不到该房间')
    # Prefer the default study area, then preserve server room order.
    rooms.sort(key=lambda r: str(r['id']) != ROOM)
    queues = []
    for info in rooms:
        seats = client.seats(info['id'], date, start, end)
        rows = sorted(seats.values(), key=lambda s: (s.get('afterFree') is not True, str(s.get('label', ''))))
        queues.append((info, rows))
    # Round-robin across rooms: avoid exhausting the budget in just one room.
    pool = []
    for index in range(max((len(rows) for _, rows in queues), default=0)):
        for info, rows in queues:
            if index < len(rows):
                pool.append((info, rows[index]))
    matches = []
    checked = 0
    for info, seat in pool:
        if checked >= max_checks or len(matches) >= limit:
            break
        checked += 1
        try:
            plan = client.validate_booking(seat['id'], date, start, end)
        except Error as exc:
            if exc.code == 'TIME_UNAVAILABLE':
                continue
            raise  # Auth/network failures must not become false "no seats" results.
        matches.append({**plan, 'roomId': str(info['id']), 'seatLabel': seat.get('label'),
                        'buildingName': info.get('buildingName'), 'floorName': info.get('floorName'),
                        'roomName': info.get('name'), 'currentStatus': seat.get('status'),
                        'reason': '服务器可选开始/结束时间均匹配，覆盖完整计划时段',
                        'checkedAt': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')})
    exhausted = checked == len(pool)
    return {'date': date, 'start': 'now' if start == -1 else f'{start//60:02d}:{start%60:02d}',
            'end': f'{end//60:02d}:{end%60:02d}',
            'scope': {'buildingId': str(building), 'floorId': str(floor), 'roomId': room,
                      'roomsSearched': len(rooms)},
            'recommendations': matches, 'checkedSeats': checked, 'candidateSeats': len(pool),
            'searchExhausted': exhausted,
            'stopReason': 'exhausted' if exhausted else ('result_limit' if len(matches) >= limit else 'check_limit'),
            'submitted': False,
            'note': '仅为查询时可选时段，不保证账号预约资格或提交时仍有空位；未创建预约。'}
