from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Date, DateTime, Boolean, Text
from .database import Base


class WeeklyReportSnapshot(Base):
    """
    Persistent store for automated weekly & historical reporting snapshots.
    Isolated in its own table so historical weekly reports are preserved
    without overwriting completed weekly baselines.
    """
    __tablename__ = "weekly_report_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    week_id = Column(String(100), nullable=False, index=True)  # e.g. WEEK-2026-11-01_2026-11-07 or ALL_WEEKS
    week_start = Column(Date, nullable=False, index=True)
    week_end = Column(Date, nullable=False, index=True)
    snapshot_version = Column(Integer, nullable=False, default=1)
    is_baseline = Column(Boolean, nullable=False, default=True)
    is_sealed = Column(Boolean, nullable=False, default=False)
    data_signature = Column(String(64), nullable=False, default="")
    summary_metrics_json = Column(Text, nullable=False, default="{}")
    report_payload_json = Column(Text, nullable=False, default="{}")
    xlsx_path = Column(Text, nullable=False, default="")
    pdf_path = Column(Text, nullable=False, default="")
    generated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_meta_dict(self):
        return {
            "id": self.id,
            "week_id": self.week_id,
            "week_start": self.week_start.isoformat() if self.week_start else "",
            "week_end": self.week_end.isoformat() if self.week_end else "",
            "snapshot_version": self.snapshot_version,
            "is_baseline": bool(self.is_baseline),
            "is_sealed": bool(self.is_sealed),
            "data_signature": self.data_signature,
            "xlsx_path": self.xlsx_path,
            "pdf_path": self.pdf_path,
            "generated_at": self.generated_at.isoformat() if self.generated_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }

