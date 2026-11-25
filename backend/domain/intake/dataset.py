from .models import ArchiveRow


def record_key(row: ArchiveRow) -> str:
    return f'{row.row_type}:{row.record_id}'


def validate_rows(rows: list[ArchiveRow]) -> None:
    if not rows:
        raise ValueError('至少提供一条观察')
    seen: set[str] = set()
    for row in rows:
        key = record_key(row)
        if key in seen:
            raise ValueError(f'观察编号重复：{key}')
        seen.add(key)
