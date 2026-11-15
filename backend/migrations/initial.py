from sqlalchemy import inspect, text
from src.config.database import Base, engine
from src import models


# create_all cannot add columns to an existing table; keep the demo stack self-upgrading.
_COLUMNS = {
    'jobs': {
        'review_status': "VARCHAR(20) NOT NULL DEFAULT 'pending'",
        'approval_batch_id': 'INT NULL',
        'review_version': 'INT NOT NULL DEFAULT 0',
    },
    'reports': {
        'approval_batch_id': 'INT NULL',
        'lifecycle': "VARCHAR(20) NOT NULL DEFAULT 'active'",
        'withdrawn_at': 'DOUBLE NULL',
        'recertified_at': 'DOUBLE NULL',
    },
    'approval_batches': {
        'approved_by_name': "VARCHAR(80) NOT NULL DEFAULT ''",
        'withdrawn_by_name': "VARCHAR(80) NOT NULL DEFAULT ''",
    },
    'deliveries': {
        'approval_batch_id': 'INT NULL',
        'withdrawn_at': 'DOUBLE NULL',
        'superseded_at': 'DOUBLE NULL',
    },
}


def _backfill():
    """Legacy rows were approved before batches existed; give them a truthful batch."""
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT id, approved, approval_batch_id, finished_at, created_at FROM jobs"
        )).mappings().all()
        for row in rows:
            if row['approval_batch_id'] or not row['approved']:
                continue
            approved_at = row['finished_at'] or row['created_at'] or 0
            conn.execute(text(
                "INSERT INTO approval_batches (job_id, status, approved_by, approved_by_name, approved_at, "
                "approve_note, withdrawn_by, withdrawn_by_name, withdrawn_at, withdraw_reason) "
                "VALUES (:job_id, 'active', :by, '历史记录', :at, :note, '', '', NULL, '')"
            ), {'job_id': row['id'], 'by': '历史批准记录', 'at': approved_at or 0.0, 'note': '批次升级前的既有批准'})
            batch_id = conn.execute(text('SELECT id FROM approval_batches ORDER BY id DESC LIMIT 1')).scalar_one()
            conn.execute(text("UPDATE jobs SET approval_batch_id=:batch, review_status='approved' WHERE id=:id"),
                         {'batch': batch_id, 'id': row['id']})
            conn.execute(text(
                "UPDATE reports SET approval_batch_id=:batch WHERE job_id=:id AND approval_batch_id IS NULL"
            ), {'batch': batch_id, 'id': row['id']})
            conn.execute(text(
                "UPDATE deliveries SET approval_batch_id=:batch WHERE approval_batch_id IS NULL AND report_id IN "
                "(SELECT id FROM reports WHERE job_id=:id)"
            ), {'batch': batch_id, 'id': row['id']})


def migrate():
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, columns in _COLUMNS.items():
            if table not in inspector.get_table_names():
                continue
            existing = {c['name'] for c in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))
    _backfill()


if __name__ == '__main__':
    migrate()
