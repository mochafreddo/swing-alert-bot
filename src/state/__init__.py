"""
State models and helpers for encrypted JSON persistence.

This package defines the in-memory schema that will be serialized,
encrypted (via Fernet in subsequent tasks), and stored in S3.
"""

from .models import State

__all__ = ["State"]

