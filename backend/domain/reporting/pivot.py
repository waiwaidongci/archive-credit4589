from collections import defaultdict


DIMENSIONS = {
    'archive_first': ('archive', 'channel', 'use_kind'),
    'channel_first': ('channel', 'archive', 'use_kind'),
}


def build_pivot(details: list[dict], dimensions: tuple[str, ...]) -> list[dict]:
    groups = {(): {'usage_count': 0, 'fee_cents': 0}}
    for row in details:
        path = tuple(row[dimension] for dimension in dimensions)
        for depth in range(len(dimensions) + 1):
            totals = groups.setdefault(path[:depth], {'usage_count': 0, 'fee_cents': 0})
            totals['usage_count'] += 1
            totals['fee_cents'] += row['fee_cents']

    return [dict(zip(dimensions, path + (None,) * (len(dimensions) - len(path))),
                 level=len(path), **totals)
            for path, totals in sorted(groups.items())]


def reconcile(pivot: list[dict], dimensions: tuple[str, ...], fee_cents: int,
              usage_count: int) -> list[dict]:
    rows = []
    child_totals = defaultdict(lambda: [0, 0])
    for row in pivot:
        if row['level']:
            parent_path = tuple(row[key] for key in dimensions[:row['level'] - 1])
            child_totals[parent_path][0] += row['fee_cents']
            child_totals[parent_path][1] += row['usage_count']

    for level in range(len(dimensions) + 1):
        group = [row for row in pivot if row['level'] == level]
        pivot_fee = sum(row['fee_cents'] for row in group)
        pivot_count = sum(row['usage_count'] for row in group)
        mismatches = 0
        if level < len(dimensions):
            for row in group:
                path = tuple(row[key] for key in dimensions[:level])
                if child_totals[path] != [row['fee_cents'], row['usage_count']]:
                    mismatches += 1
        rows.append({'level': level, 'detail_fee_cents': fee_cents, 'pivot_fee_cents': pivot_fee,
                     'fee_delta_cents': pivot_fee - fee_cents, 'detail_usage_count': usage_count,
                     'pivot_usage_count': pivot_count, 'usage_count_delta': pivot_count - usage_count,
                     'parent_mismatch_count': mismatches,
                     'balanced': pivot_fee == fee_cents and pivot_count == usage_count and mismatches == 0})
    return rows
