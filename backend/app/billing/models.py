from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.clock import now_utc
from app.database import Base


class Settlement(Base):
    """一份补退款出账记录：已出账批次被一份修订批次接续一次。"""

    __tablename__ = 'settlements'
    __table_args__ = (UniqueConstraint('base_run_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    base_run_id: Mapped[int] = mapped_column(ForeignKey('analysis_runs.id'), index=True)
    revision_run_id: Mapped[int] = mapped_column(ForeignKey('analysis_runs.id'), index=True)
    posted_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    # 出账当时冻结的报告快照，之后无论上游如何修订都按原样查回。
    report: Mapped[dict] = mapped_column(JSON)
