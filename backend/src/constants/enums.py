from enum import Enum
class Role(str, Enum):
    admin = 'admin'
    analyst = 'analyst'
    viewer = 'viewer'
class JobStatus(str, Enum):
    queued = 'queued'
    running = 'running'
    completed = 'completed'
    failed = 'failed'
class ReviewStatus(str, Enum):
    pending = 'pending'
    approved = 'approved'
    withdrawn = 'withdrawn'
class ApprovalBatchStatus(str, Enum):
    active = 'active'
    withdrawn = 'withdrawn'
