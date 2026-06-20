"""Hardware-locked, offline license enforcement for the Pharmacy System.

See LICENSING.md for the full per-client activation workflow.
"""

from . import gate
from .fingerprint import machine_id

__all__ = ["gate", "machine_id"]
