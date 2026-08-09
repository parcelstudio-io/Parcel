"""Select synthetic vs MuJoCo-EGL CameraBackend for CI vs local sim."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

from parcel_robot.camera_channel.backends.mujoco_egl import (
    MujocoEglCameraBackend,
    MujocoEglUnavailable,
)
from parcel_robot.camera_channel.backends.synthetic import SyntheticCameraBackend
from parcel_robot.camera_channel.channel import CameraBackend, CameraChannel, CameraChannelSpec

BackendKind = Literal["synthetic", "mujoco_egl"]

_PROBE_CACHE: ProbeResult | None = None

DOES_NOT_PROVE = (
    "MuJoCo EGL/OSMesa renders are synthetic pixels — not D455 field validation "
    "(hardware-readiness HR-4).",
    "CI synthetic backends prove envelope wiring only, not perception accuracy.",
)


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Outcome of an in-process MuJoCo offscreen probe."""

    available: bool
    detail: str
    mujoco_gl: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "available": self.available,
            "detail": self.detail,
            "mujoco_gl": self.mujoco_gl,
            "does_not_prove": list(DOES_NOT_PROVE),
        }


def probe_mujoco_offscreen(*, force: bool = False) -> ProbeResult:
    """Try a tiny ``mujoco.Renderer``; cache so CI stays cheap.

    Note: MuJoCo binds the GL backend at first import from ``MUJOCO_GL``.
    Setting the env var after import has no effect in this process.
    """

    global _PROBE_CACHE
    if _PROBE_CACHE is not None and not force:
        return _PROBE_CACHE

    gl = os.environ.get("MUJOCO_GL")
    try:
        import mujoco
    except Exception as exc:  # noqa: BLE001
        result = ProbeResult(False, f"mujoco import failed: {exc}", gl)
        _PROBE_CACHE = result
        return result

    xml = (
        '<mujoco><worldbody><light pos="0 0 2"/>'
        '<geom type="plane" size="1 1 0.1"/>'
        '<body pos="0 0 0.2"><geom type="sphere" size="0.05" rgba="1 0 0 1"/>'
        "</body></worldbody></mujoco>"
    )
    try:
        model = mujoco.MjModel.from_xml_string(xml)
        data = mujoco.MjData(model)
        mujoco.mj_forward(model, data)
        renderer = mujoco.Renderer(model, height=32, width=32)
        try:
            renderer.update_scene(data)
            rgb = renderer.render()
            if rgb is None or getattr(rgb, "shape", None) != (32, 32, 3):
                raise RuntimeError(f"unexpected render shape: {getattr(rgb, 'shape', None)}")
        finally:
            try:
                renderer.close()
            except Exception:  # noqa: BLE001
                pass
        result = ProbeResult(
            True,
            f"mujoco.Renderer ok (MUJOCO_GL={gl!r})",
            gl,
        )
    except Exception as exc:  # noqa: BLE001
        result = ProbeResult(
            False,
            f"offscreen unavailable (MUJOCO_GL={gl!r}): {exc}",
            gl,
        )
    _PROBE_CACHE = result
    return result


def open_camera_backend(
    spec: CameraChannelSpec | None = None,
    *,
    prefer: Literal["auto", "synthetic", "mujoco_egl"] = "auto",
    model: Any | None = None,
    data: Any | None = None,
    class_ids: tuple[str, ...] = ("background", "person", "sign", "curb"),
    seed: int = 0,
    robot_body_name: str | None = None,
) -> tuple[CameraBackend, BackendKind]:
    """Construct a CameraBackend.

    ``prefer="auto"`` uses MuJoCo EGL when a probe succeeds **and** model/data
    are supplied; otherwise synthetic. CI should pass ``prefer="synthetic"``
    (or omit model/data) so the suite stays green without GL.
    """

    channel_spec = spec if spec is not None else CameraChannelSpec.d455_go2_nominal()

    if prefer == "synthetic":
        return (
            SyntheticCameraBackend(channel_spec, class_ids=class_ids, seed=seed),
            "synthetic",
        )

    if prefer == "mujoco_egl":
        if model is None or data is None:
            raise MujocoEglUnavailable("mujoco_egl prefer requires model and data")
        return (
            MujocoEglCameraBackend(
                model,
                data,
                spec=channel_spec,
                class_ids=class_ids,
                robot_body_name=robot_body_name,
            ),
            "mujoco_egl",
        )

    # auto
    if model is not None and data is not None and probe_mujoco_offscreen().available:
        try:
            return (
                MujocoEglCameraBackend(
                    model,
                    data,
                    spec=channel_spec,
                    class_ids=class_ids,
                    robot_body_name=robot_body_name,
                ),
                "mujoco_egl",
            )
        except MujocoEglUnavailable:
            pass
    return (
        SyntheticCameraBackend(channel_spec, class_ids=class_ids, seed=seed),
        "synthetic",
    )


def attach_preferred_backend(
    channel: CameraChannel,
    *,
    prefer: Literal["auto", "synthetic", "mujoco_egl"] = "auto",
    model: Any | None = None,
    data: Any | None = None,
    class_ids: tuple[str, ...] = ("background", "person", "sign", "curb"),
    seed: int = 0,
    robot_body_name: str | None = None,
) -> BackendKind:
    """Attach a backend to an existing CameraChannel; return the kind used."""

    backend, kind = open_camera_backend(
        channel.spec,
        prefer=prefer,
        model=model,
        data=data,
        class_ids=class_ids,
        seed=seed,
        robot_body_name=robot_body_name,
    )
    channel.attach_backend(backend)
    return kind
