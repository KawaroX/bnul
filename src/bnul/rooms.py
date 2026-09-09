"""Persistent building-scoped room numbers and human-readable selectors."""
import json
import os
import re
import tempfile
from .client import Error, config_path, day, identifier


def normalized(value):
    return re.sub(r'[\s（）()、,，_-]', '', str(value)).casefold()


def short_name(name):
    return re.split(r'[（(]', name)[0].strip()


def room_catalog(client, building, refresh=False):
    building = identifier(building)
    path = config_path().parent / f'rooms-{building}.json'
    old = {'rooms': []}
    try:
        old = json.loads(path.read_text(encoding='utf-8'))
        if old.get('version') != 1 or not isinstance(old.get('rooms'), list):
            raise ValueError()
    except FileNotFoundError:
        pass
    except (ValueError, TypeError):
        raise Error(f'房间编号缓存损坏，请检查 {path}；为避免编号误指不会自动重建') from None
    if not refresh and old.get('updatedDate') == day('today'):
        return old
    live = client.rooms(building, day('today'), 0, 0)
    records = {str(r['id']): dict(r, active=False) for r in old['rooms']}
    number = max((r['number'] for r in old['rooms']), default=0)
    for info in live:
        rid = str(info['id'])
        if rid not in records:
            number += 1
            records[rid] = {'id': rid, 'number': number}
        n = records[rid]['number']
        records[rid].update({'name': info['name'], 'shortName': short_name(info['name']),
                            'alias': f'r{n}', 'buildingId': building,
                            'floorId': str(info.get('floorId', '')), 'floorName': info.get('floorName'),
                            'active': True})
    result = {'version': 1, 'buildingId': building, 'updatedDate': day('today'),
              'rooms': sorted(records.values(), key=lambda r: r['number'])}
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.rooms-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return result


def resolve_room(value, catalog):
    value = value.strip()
    rows = [r for r in catalog['rooms'] if r['active']]
    # IDs are distinguished from small local indices by exact match first.
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
