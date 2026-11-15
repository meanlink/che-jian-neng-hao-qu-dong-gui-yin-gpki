from sqlalchemy import String, JSON, Double, ForeignKey, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class Job(Base):
    __tablename__ = 'jobs'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default='queued')
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(String(1000), default='')
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    review_status: Mapped[str] = mapped_column(String(20), default='pending')
    approval_batch_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # incremented on every successful withdraw / resubmit so stale approvals are rejected
    review_version: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)


class ApprovalBatch(Base):
    """One immutable approval decision. Re-approval after withdrawal creates a new row."""
    __tablename__ = 'approval_batches'
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'), index=True)
    status: Mapped[str] = mapped_column(String(20), default='active')
    approved_by: Mapped[str] = mapped_column(String(150), default='')
    approved_by_name: Mapped[str] = mapped_column(String(80), default='')
    approved_at: Mapped[float] = mapped_column(Double)
    approve_note: Mapped[str] = mapped_column(String(500), default='')
    withdrawn_by: Mapped[str] = mapped_column(String(150), default='')
    withdrawn_by_name: Mapped[str] = mapped_column(String(80), default='')
    withdrawn_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    withdraw_reason: Mapped[str] = mapped_column(String(500), default='')
