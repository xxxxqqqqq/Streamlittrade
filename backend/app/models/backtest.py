"""回测请求、参数与结果元数据模型。"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, JSON, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


class BacktestRun(Base):
    """保存可查询的小型元数据；大型明细放入MinIO/OSS。"""

    __tablename__ = "backtest_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    data_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("data_versions.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    strategy_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("strategies.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_versions.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    signal_source: Mapped[str] = mapped_column(String(30), nullable=False, default="strategy")
    portfolio_construction: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    run_type: Mapped[str] = mapped_column(String(20), nullable=False, default="single")
    data_source: Mapped[str] = mapped_column(String(30), nullable=False)
    # Portfolio runs persist the comma-separated research universe for a compact
    # list view; the complete immutable request also remains in the artifact.
    symbol: Mapped[str] = mapped_column(String(1000), nullable=False, index=True)
    strategy_name: Mapped[str] = mapped_column(String(50), nullable=False)
    strategy_parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    initial_cash: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    data_quality: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    artifact_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    job: Mapped["Job"] = relationship(back_populates="backtest_run")
