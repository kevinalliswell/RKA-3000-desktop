from __future__ import annotations


class DeviceCommError(RuntimeError):
    """Raised by a device adapter when a read/write to its device fails."""
