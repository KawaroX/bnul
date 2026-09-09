"""Read-only, bounded search for seats covering the exact requested interval."""
from datetime import datetime
from zoneinfo import ZoneInfo
from .client import BUILDING, Error, day, identifier, query_start


def recommend(client, date, start, end, building=BUILDING, room=None, floor='0',
              limit=5, max_checks=50, room_order=None):
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
    if room_order:
        if room:
            raise Error('room 和 room-order 不能同时使用')
        by_id = {str(r['id']): r for r in rooms}
        missing = [rid for rid in room_order if rid not in by_id]
        if missing:
            raise Error('指定顺序中的房间不在楼馆/楼层结果内：' + ', '.join(missing))
        rooms = [by_id[rid] for rid in room_order]
    queues = []
    for info in rooms:
        seats = client.seats(info['id'], date, start, end)
        rows = sorted(seats.values(), key=lambda s: (s.get('afterFree') is not True, str(s.get('label', ''))))
        queues.append((info, rows))
    pool = []
    if room_order:
        # Strict priority: only move on after checking all candidates in a room.
        pool = [(info, seat) for info, rows in queues for seat in rows]
    else:
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
                      'roomsSearched': len(rooms), 'roomOrder': room_order,
                      'strategy': 'priority' if room_order else 'round_robin'},
            'recommendations': matches, 'checkedSeats': checked, 'candidateSeats': len(pool),
            'searchExhausted': exhausted,
            'stopReason': 'exhausted' if exhausted else ('result_limit' if len(matches) >= limit else 'check_limit'),
            'submitted': False,
            'note': '仅为查询时可选时段，不保证账号预约资格或提交时仍有空位；未创建预约。'}
