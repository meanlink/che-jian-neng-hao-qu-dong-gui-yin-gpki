from sqlalchemy import String, Double, ForeignKey, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class Report(Base):
    __tablename__ = 'reports'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'))
    destination: Mapped[str] = mapped_column(String(120))
    interval_seconds: Mapped[int]
    next_run: Mapped[float] = mapped_column(Double)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    approval_batch_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # withdrawn: 计划随结论撤回而失效；certified: 结论已重新批准且批次匹配，可再次投递
    lifecycle: Mapped[str] = mapped_column(String(20), default='active')
    withdrawn_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    recertified_at: Mapped[float | None] = mapped_column(Double, nullable=True)


class Delivery(Base):
    __tablename__ = 'deliveries'
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey('reports.id'))
    created_at: Mapped[float] = mapped_column(Double)
    checksum: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(160))
    destination: Mapped[str] = mapped_column(String(120))
    # 归档属于哪一批准批次；批次撤回后文件仍留审计，但拒绝下载
    approval_batch_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # sealed：撤回生效时已开始的下载可结束；其余请求按撤回批次校验拒绝
    withdrawn_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    superseded_at: Mapped[float | None] = mapped_column(Double, nullable=True)
