"""Default-off, summary-only research data plane.

This package is deliberately separate from companion memory and robot control.
Importing it performs no I/O.  A caller must explicitly enable
:class:`ResearchPlane`, choose a dedicated root, and submit an event through
the strict v1 admission boundary before any bytes are persisted.

The package stops at locally verified, content-addressed bundles.  It contains
no network client and will not authorize a plaintext object for upload.

The public classes live in explicit leaf modules (``contracts``, ``admission``,
``spool``, ``bundle``, ``governor``, and ``pipeline``).  Keeping this initializer
import-free prevents a package-edge cycle and, more importantly, guarantees
that importing the namespace cannot initialize storage.
"""
