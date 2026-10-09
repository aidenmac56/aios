"""Closed sets used across the schema. Stored as strings with CHECK constraints."""

from enum import StrEnum


class MemoryStatus(StrEnum):
    EXPLICIT = "EXPLICIT"        # founder said it
    CONFIRMED = "CONFIRMED"      # repeated founder decisions support it
    INFERRED = "INFERRED"        # system believes it may be true
    HYPOTHESIS = "HYPOTHESIS"    # weak evidence only
    SUPERSEDED = "SUPERSEDED"    # no longer authoritative


class Provenance(StrEnum):
    FOUNDER = "FOUNDER"
    INTERNAL_DATABASE = "INTERNAL_DATABASE"
    AGENT_INFERENCE = "AGENT_INFERENCE"
    EXTERNAL_RESEARCH = "EXTERNAL_RESEARCH"
    FINANCIAL_IMPORT = "FINANCIAL_IMPORT"
    TOOL_OUTPUT = "TOOL_OUTPUT"
    SYSTEM_OBSERVATION = "SYSTEM_OBSERVATION"
    OTHER_AGENT = "OTHER_AGENT"


class MemoryCategory(StrEnum):
    FOUNDER = "FOUNDER"
    COMPANY = "COMPANY"
    PROJECT = "PROJECT"
    RESEARCH = "RESEARCH"
    DECISION = "DECISION"
    FINANCIAL = "FINANCIAL"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"


class TaskStatus(StrEnum):
    PROPOSED = "PROPOSED"
    PLANNED = "PLANNED"
    WAITING = "WAITING"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    READY = "READY"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TaskKind(StrEnum):
    PLAN = "PLAN"   # a real-world task in a project
    WORK = "WORK"   # an agent work item inside a workflow run


class ProjectStatus(StrEnum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"          # finished with some agent failures or stopped by budget
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"


class TxnStatus(StrEnum):
    ACTUAL = "ACTUAL"
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"


class ForecastKind(StrEnum):
    FORECAST = "FORECAST"
    ESTIMATE = "ESTIMATE"


class DecisionStatus(StrEnum):
    PROPOSED = "PROPOSED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ApprovalType(StrEnum):
    SPEND = "SPEND"
    COMMUNICATE = "COMMUNICATE"
    DELETE = "DELETE"
    PRODUCTION_CHANGE = "PRODUCTION_CHANGE"
    SYSTEM_CHANGE = "SYSTEM_CHANGE"
    PUBLISH = "PUBLISH"
    CONTRACT = "CONTRACT"
    DECISION = "DECISION"
    PLAN = "PLAN"


class AuditVerdict(StrEnum):
    PASS = "PASS"
    PASS_WITH_CONDITIONS = "PASS_WITH_CONDITIONS"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCK = "BLOCK"


class ImprovementStatus(StrEnum):
    PROPOSED = "PROPOSED"
    TESTING = "TESTING"
    TESTED = "TESTED"
    APPROVED = "APPROVED"
    IMPLEMENTED = "IMPLEMENTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    ROLLED_BACK = "ROLLED_BACK"


class Credibility(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Confidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ModelTier(StrEnum):
    FAST = "FAST"
    BALANCED = "BALANCED"
    DEEP = "DEEP"


class MediaKind(StrEnum):
    VOICE_REFERENCE = "VOICE_REFERENCE"  # the founder's own recording a voice is cloned from
    AVATAR_SOURCE = "AVATAR_SOURCE"  # the founder's own on-camera footage the avatar is lip-synced onto
    VOICE_AUDIO = "VOICE_AUDIO"  # generated speech
    AVATAR_VIDEO = "AVATAR_VIDEO"  # generated talking-head video


class MediaStatus(StrEnum):
    ACTIVE = "ACTIVE"  # a reference/source currently in use
    RETIRED = "RETIRED"  # a reference/source replaced by a newer one
    DRAFT = "DRAFT"  # generated output waiting for the founder's review
    FAILED = "FAILED"
