"""Vendor-neutral locomotion control.

This package intentionally contains no vendor imports at module scope.
Vendor adapters (Unitree Sport, future robots) live in their own modules and
are reached exclusively through the controller registry in ``factory``.
"""
