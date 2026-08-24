"""Opus CameraBackend implementations (MuJoCo EGL + CI synthetic).

Sol owns the pure ``CameraBackend`` protocol. This package fills envelopes:

- ``SyntheticCameraBackend`` — deterministic RGB/depth/seg for CI (always).
- ``MujocoEglCameraBackend`` — offscreen MuJoCo render when EGL/OSMesa works.

The real-EGL path is **sim evidence only** (hardware-readiness HR-4). It does
not validate D455 optics or field low-viewpoint perception.
"""
