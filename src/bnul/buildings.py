"""Stable building numbers and live human-readable selectors."""
import re

from .client import Error
from .floors import direct_floor, floor_catalog_row, floor_selector
from .rooms import normalized, short_name


# Public numbers are permanent; never reuse a removed building's number.
FIXED_BUILDINGS = {
    '1887388460760797184': 1,
    '1864245010251223040': 2,
    '1887389250929922048': 3,
    '2067149686880440320': 4,
}


def building_catalog(client):
    """Add selectors to the live catalog without changing the API response."""
    live = client.api('res/buildingFloorDate')
    rows = []
    for info in live['buildings']:
        number = FIXED_BUILDINGS.get(str(info['id']))
        row = {**info, 'number': number,
               'alias': f'b{number}' if number is not None else None,
               'shortName': short_name(info['name'])}
        if 'floors' in info:
            row['floors'] = [floor_catalog_row(floor) for floor in info['floors']]
        rows.append(row)
    return {**live, 'buildings': rows}


def resolve_building(value, catalog):
    value = value.strip()
    rows = catalog['buildings']
    matches = [row for row in rows if str(row['id']) == value]
    if not matches:
        if value.isdigit() or re.fullmatch(r'b\d+', value, re.I):
            number = int(value.lstrip('bB'))
            matches = [row for row in rows if row['number'] == number]
        else:
            key = normalized(value)
            if not key:
                raise Error('楼馆名称不能为空', 'BUILDING_NOT_FOUND')
            # Full names win before short names, so 主馆 never selects 主馆南区.
            matches = [row for row in rows if key == normalized(row['name'])]
            if not matches:
                matches = [row for row in rows if key == normalized(row['shortName'])]
            if not matches:
                matches = [row for row in rows if key in normalized(row['name'])]
    if len(matches) == 1:
        row = matches[0]
        if not row.get('enabled', True):
            raise Error(f"楼馆 {row['name']} 当前未启用，请运行 buildings 查看最新清单", 'BUILDING_DISABLED')
        return str(row['id'])
    if matches:
        choices = '、'.join(
            f"{row['alias'] or row['id']}: {row['name']}"
            for row in matches)
        raise Error('楼馆名称有歧义，请选择：' + choices, 'BUILDING_AMBIGUOUS')
    raise Error(f'找不到楼馆 {value}，请运行 buildings 查看固定别名与 ID', 'BUILDING_NOT_FOUND')


def building_selector(client, value, catalog=None):
    value = value.strip()
    # Preserve existing full-ID scripts without adding a catalog request.
    if re.fullmatch(r'\d{12,}', value):
        return value
    if catalog is None:
        catalog = building_catalog(client)
    return resolve_building(value, catalog)


def location_selector(client, building, floor=None):
    """Resolve both selectors using at most one live directory request."""
    catalog = None
    if not re.fullmatch(r'\d{12,}', building.strip()) or (floor is not None and direct_floor(floor) is None):
        catalog = building_catalog(client)
    building = building_selector(client, building, catalog)
    if floor is not None:
        floor = floor_selector(client, building, floor, catalog)
    return building, floor
