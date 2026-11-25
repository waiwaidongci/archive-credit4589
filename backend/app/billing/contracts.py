from pydantic import BaseModel, ConfigDict, Field


class SettlementRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    base_run_id: int = Field(ge=1)
    revision_run_id: int = Field(ge=1)
