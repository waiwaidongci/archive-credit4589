from datetime import date
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


RecordType = Literal['contract', 'rate', 'usage']
Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Seconds = Annotated[int, Field(ge=1, le=86_400)]
RateCents = Annotated[int, Field(ge=0, le=10_000_000)]

TYPE_FIELDS = {
    'contract': ('starts_on', 'ends_on'),
    'rate': ('effective_on', 'unit_seconds', 'rate_cents'),
    'usage': ('contract_id', 'asset', 'used_on', 'usage_seconds'),
}


class ArchiveRow(BaseModel):
    """合同需填 starts_on、ends_on，费率需填 effective_on、unit_seconds、rate_cents，
    使用需填 contract_id、asset、used_on、usage_seconds。其他类型的专属列留空。
    """

    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

    row_type: RecordType
    record_id: Identifier
    archive: Label
    channel: Label
    use_kind: Label
    starts_on: date | None = None
    ends_on: date | None = None
    effective_on: date | None = None
    unit_seconds: Seconds | None = None
    rate_cents: RateCents | None = None
    contract_id: Identifier | None = None
    asset: Label | None = None
    used_on: date | None = None
    usage_seconds: Seconds | None = None

    @field_validator('starts_on', 'ends_on', 'effective_on', 'used_on', mode='before')
    @classmethod
    def calendar_date(cls, value):
        if value is None or type(value) is date:
            return value
        if isinstance(value, str) and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
            return value
        raise ValueError('Use a YYYY-MM-DD calendar date')

    @field_validator('unit_seconds', 'rate_cents', 'usage_seconds', mode='before')
    @classmethod
    def reject_boolean_numbers(cls, value):
        if isinstance(value, bool):
            raise ValueError('Use an integer value')
        return value

    @model_validator(mode='after')
    def check_type_fields(self):
        required = TYPE_FIELDS[self.row_type]
        missing = [field for field in required if getattr(self, field) is None]
        if missing:
            raise ValueError(f'{self.row_type} requires {", ".join(missing)}')
        unexpected = [field for row_type, fields in TYPE_FIELDS.items() if row_type != self.row_type
                      for field in fields if getattr(self, field) is not None]
        if unexpected:
            raise ValueError(f'{self.row_type} does not use {", ".join(unexpected)}')
        return self

    def scope(self) -> tuple[str, str, str]:
        return self.archive, self.channel, self.use_kind


class PivotOptions(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

    pivot_order: Literal['archive_first', 'channel_first'] = 'archive_first'
