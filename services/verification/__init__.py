"""Workspace-bounded execution for verification checks."""

# Keep package initialization light: repair report types import the outcome type,
# while the executor imports repair report types.
from services.verification.types import VerificationCommand, VerificationOutcome

__all__ = ["VerificationCommand", "VerificationOutcome"]
