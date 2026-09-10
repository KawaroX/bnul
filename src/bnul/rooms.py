"""Shared fixed room numbers and human-readable selectors."""
import re
from .client import Error, day, identifier

# Public numbers are permanent; never reuse a removed room's number.
FIXED_ROOMS = {'1887388460760797184': {
    '1877586363089522688': 1,
    '1887370822454185984': 2,
    '1887410836445696000': 3,
    '1888096971220160512': 4,
    '1888143784337838080': 5,
    '1891313130644017152': 6,
    '1888818842819465216': 7,
    '1888163731197759488': 8,
    '1888125623479668736': 9,
}}


def normalized(value):
    return re.sub(r'[\s（）()、,，_-]', '', str(value)).casefold()


def short_name(name):
    return re.split(r'[（(]', name)[0].strip()


def room_catalog(client, building, refresh=False):
    building = identifier(building)
    # refresh remains accepted for callers; local numbering caches are ignored.
    live = client.rooms(building, day('today'), 0, 0)
    records = {}
    for info in live:
        rid = str(info['id'])
        n = FIXED_ROOMS.get(building, {}).get(rid)
        records[rid] = {'id': rid, 'number': n,
                            'name': info['name'], 'shortName': short_name(info['name']),
                            'alias': f'r{n}' if n is not None else None, 'buildingId': building,
                            'floorId': str(info.get('floorId', '')), 'floorName': info.get('floorName'),
                            'active': True}
    return {'version': 2, 'buildingId': building, 'updatedDate': day('today'),
            'rooms': sorted(records.values(), key=lambda r: (r['number'] is None, r['number'] or 0, r['id']))}


def resolve_room(value, catalog):
    value = value.strip()
    rows = [r for r in catalog['rooms'] if r['active']]
    # IDs are distinguished from fixed numbers by exact match first.
    exact_id = [r for r in rows if r['id'] == value]
    if exact_id:
        return exact_id[0]['id']
    if value.isdigit() or re.fullmatch(r'r\d+', value, re.I):
        n = int(value.lstrip('rR'))
        n = 10 if n == 0 else n
        matches = [r for r in rows if r['number'] == n]
    else:
        key = normalized(value)
        if not key:
            raise Error('房间名称不能为空')
        matches = [r for r in rows if key in {normalized(r['name']), normalized(r['shortName'])}]
        if not matches:
            matches = [r for r in rows if key in normalized(r['name'])]
    if len(matches) == 1:
        return matches[0]['id']
    if matches:
        choices = '、'.join(f"{r['number']}: {r['name']}" for r in matches)
        raise Error('房间名称有歧义，请选择：' + choices, 'ROOM_AMBIGUOUS')
    raise Error(f'找不到房间 {value}，请运行 room-list 查看当前编号与名称', 'ROOM_NOT_FOUND')


def room_selector(client, building, value):
    # Preserve existing full-ID scripts without adding a catalog request.
    if re.fullmatch(r'\d{12,}', value):
        return value
    return resolve_room(value, room_catalog(client, building))


def ordered_rooms(client, building, order=None, sequence=None):
    if sequence is not None:
        if not re.fullmatch(r'[0-9]+', sequence):
            raise Error('room-sequence 只接受数字，例如 432；0 表示第 10 项')
        tokens = list(sequence)
    else:
        tokens = [part.strip() for part in re.split('[,，]', order or '')]
    if not tokens or any(not token for token in tokens):
        raise Error('room-order 需要逗号分隔的房间序号或名称')
    catalog = room_catalog(client, building)
    selected = [resolve_room(token, catalog) for token in tokens]
    if len(set(selected)) != len(selected):
        raise Error('搜索顺序包含重复房间，请移除重复项')
    return selected
