"""Typed failures. Every one of these is shown to the founder; none is swallowed."""


class AIOSError(Exception):
    code = "error"

    def __init__(self, message: str, **details):
        super().__init__(message)
        self.message = message
        self.details = details

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, **self.details}


class PermissionDenied(AIOSError):
    code = "permission_denied"


class ApprovalRequired(AIOSError):
    code = "approval_required"


class BudgetExceeded(AIOSError):
    code = "budget_exceeded"


class MissingCredentials(AIOSError):
    code = "missing_credentials"


class ModelError(AIOSError):
    """Provider/API failure after bounded retries."""

    code = "model_error"


class MalformedOutput(AIOSError):
    """Model output did not validate against the agent's schema after the bounded retry."""

    code = "malformed_output"


class InvalidPlan(AIOSError):
    code = "invalid_plan"


class ValidationFailed(AIOSError):
    code = "validation_failed"


class NotFound(AIOSError):
    code = "not_found"
