"""Resolve actual floor levels within a selected building."""
import re

from .client import Error
from .rooms import short_name


CHINESE_DIGITS = {'一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
                  '六': 6, '七': 7, '八': 8, '九': 9}


def normalized_floor(value):
    # Keep a minus sign significant: an unrecognized -1层 must never select 1层.
    return re.sub(r'[\s（）()、,，_]', '', str(value)).casefold()


def chinese_number(value):
    if value in CHINESE_DIGITS:
        return CHINESE_DIGITS[value]
    match = re.fullmatch(r'([一二三四五六七八九]?)十([一二三四五六七八九]?)', value)
    if match:
        return CHINESE_DIGITS.get(match[1], 1) * 10 + CHINESE_DIGITS.get(match[2], 0)
    return None


def floor_number(value):
    """Recognize a whole floor label; never infer a level from list position."""
    value = re.sub(r'\s', '', value).casefold()
    match = re.fullmatch(r'(?:f([0-9]+)|([0-9]+)f|(?:第)?([0-9]+)(?:层|楼)?|(?:第)?([一二两三四五六七八九十]+)(?:层|楼))', value)
    if not match:
        return None
    number = next((int(group) for group in match.groups()[:3] if group is not None), None)
    if number is None:
        number = chinese_number(match[4])
    return number if number is not None and number > 0 else None


def floor_catalog_row(info):
    number = floor_number(short_name(info['name']))
    return {**info, 'number': number, 'alias': f'f{number}' if number is not None else None,
            'shortName': short_name(info['name'])}


def direct_floor(value):
    value = value.strip()
    if value.casefold() in ('0', 'all', '全部'):
        return '0'
    if re.fullmatch(r'\d{12,}', value):
        return value
    return None


def resolve_floor(building, value, catalog):
    value = value.strip()
    direct = direct_floor(value)
    if direct is not None:
        return direct
    buildings = [row for row in catalog['buildings'] if str(row['id']) == str(building)]
    if not buildings:
        raise Error('找不到所选楼馆，请运行 buildings 查看最新清单', 'BUILDING_NOT_FOUND')
    selected = buildings[0]
    if not selected.get('enabled', True):
        raise Error(f"楼馆 {selected['name']} 当前未启用，请运行 buildings 查看最新清单", 'BUILDING_DISABLED')
    rows = selected.get('floors', [])
    matches = [row for row in rows if str(row['id']) == value]
    if not matches:
        key = normalized_floor(value)
        if not key:
            raise Error('楼层名称不能为空', 'FLOOR_NOT_FOUND')
        matches = [row for row in rows if key == normalized_floor(row['name'])]
    if not matches:
        number = floor_number(value)
        if number is not None:
            matches = [row for row in rows if row['number'] == number]
        elif re.fullmatch(r'(?:f[0-9]+|[0-9]+f|[0-9]+(?:层|楼)?)', value, re.I):
            # Invalid numeric selectors (such as f0) must not become name fragments.
            matches = []
        else:
            matches = [row for row in rows if key == normalized_floor(row['shortName'])]
            if not matches:
                matches = [row for row in rows if key in normalized_floor(row['name'])]
    if len(matches) == 1:
        row = matches[0]
        if not row.get('enabled', True):
            raise Error(f"楼层 {row['name']} 当前未启用，请运行 buildings 查看最新清单", 'FLOOR_DISABLED')
        return str(row['id'])
    if matches:
        choices = '、'.join(f"{row['alias'] or row['id']}: {row['name']}" for row in matches)
        raise Error('楼层名称有歧义，请选择：' + choices, 'FLOOR_AMBIGUOUS')
    raise Error(f"在楼馆 {selected['name']} 中找不到楼层 {value}，请运行 buildings 查看最新清单", 'FLOOR_NOT_FOUND')


def floor_selector(client, building, value, catalog=None):
    direct = direct_floor(value)
    if direct is not None:
        return direct
    if catalog is None:
        from .buildings import building_catalog
        catalog = building_catalog(client)
    return resolve_floor(building, value, catalog)
