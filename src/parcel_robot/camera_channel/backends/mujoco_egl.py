"""MuJoCo offscreen (EGL/OSMesa) CameraBackend — HR-4 sim pixels only."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from parcel_robot.camera_channel.backends.synthetic import CaptureBuffers
from parcel_robot.camera_channel.channel import CameraChannel, CameraChannelSpec
from parcel_robot.camera_channel.frames import CameraFrameEnvelope


class MujocoEglUnavailable(RuntimeError):
    """Raised when MuJoCo cannot create an offscreen GL context in-process."""


class MujocoEglCameraBackend:
    """Render RGB (+ depth + optional seg) via ``mujoco.Renderer``.

    Requires a working offscreen GL stack (typically ``MUJOCO_GL=egl`` set
    **before** the first ``import mujoco`` in the process). CI without EGL must
    use ``SyntheticCameraBackend`` instead.

    Honesty: rendered pixels are MuJoCo-synthetic. Passing low-viewpoint gates
    on these frames does **not** prove D455 field performance (HR-4).
    """

    kind = "mujoco_egl"

    def __init__(
        self,
        model: Any,
        data: Any,
        *,
        spec: CameraChannelSpec | None = None,
        class_ids: tuple[str, ...] = ("background", "geom"),
        robot_body_name: str | None = None,
    ) -> None:
        import mujoco

        if model is None or data is None:
            raise TypeError("model and data are required")
        self._mujoco = mujoco
        self._model = model
        self._data = data
        self._channel = CameraChannel(spec)
        self._class_ids = tuple(class_ids)
        self._buffers: dict[str, np.ndarray] = {}
        self._last: CaptureBuffers | None = None
        self._robot_body_id = -1
        if robot_body_name:
            self._robot_body_id = int(
                mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, robot_body_name)
            )

        intr = self._channel.spec.intrinsics
        try:
            # D455-nominal 1280×720 exceeds MuJoCo's default 640×480 offscreen FB.
            self._model.vis.global_.offwidth = max(
                int(self._model.vis.global_.offwidth), intr.width_px
            )
            self._model.vis.global_.offheight = max(
                int(self._model.vis.global_.offheight), intr.height_px
            )
            self._renderer = mujoco.Renderer(
                model, height=intr.height_px, width=intr.width_px
            )
        except Exception as exc:  # noqa: BLE001 — surface as typed unavailable
            raise MujocoEglUnavailable(
                "MuJoCo Renderer failed; set MUJOCO_GL=egl (or osmesa) before "
                f"importing mujoco, or use SyntheticCameraBackend ({exc})"
            ) from exc

    @property
    def spec(self) -> CameraChannelSpec:
        return self._channel.spec

    @property
    def last_buffers(self) -> CaptureBuffers | None:
        return self._last

    def get_buffer(self, blob_ref: str) -> np.ndarray:
        try:
            return self._buffers[blob_ref]
        except KeyError as exc:
            raise KeyError(f"unknown blob_ref: {blob_ref!r}") from exc

    def close(self) -> None:
        renderer = getattr(self, "_renderer", None)
        if renderer is not None:
            try:
                renderer.close()
            except Exception:  # noqa: BLE001 — teardown best-effort
                pass
            self._renderer = None

    def capture(
        self,
        *,
        source_timestamp_ns: int,
        sequence: int,
        scene_revision: int = 0,
        robot_x: float | None = None,
        robot_y: float | None = None,
        robot_yaw_rad: float | None = None,
    ) -> CameraFrameEnvelope:
        """Capture synchronized envelopes.

        Extra robot pose kwargs are accepted for mount-aligned free-camera
        placement; the ``CameraBackend`` protocol only requires the timestamp
        trio — callers that only pass those still get a valid render.
        """

        mujoco = self._mujoco
        mujoco.mj_forward(self._model, self._data)
        camera = self._free_camera(robot_x, robot_y, robot_yaw_rad)
        self._renderer.update_scene(self._data, camera=camera)

        color = np.asarray(self._renderer.render(), dtype=np.uint8).copy()
        self._renderer.enable_depth_rendering()
        self._renderer.update_scene(self._data, camera=camera)
        depth_raw = np.asarray(self._renderer.render(), dtype=np.float32).copy()
        self._renderer.disable_depth_rendering()

        # MuJoCo depth is distance along the ray; clip to D455-like band.
        depth = np.clip(
            depth_raw,
            self._channel.spec.depth_min_m,
            self._channel.spec.depth_max_m,
        ).astype(np.float32)

        seg: np.ndarray | None = None
        if self._channel.spec.include_segmentation:
            self._renderer.enable_segmentation_rendering()
            self._renderer.update_scene(self._data, camera=camera)
            seg_raw = np.asarray(self._renderer.render())
            self._renderer.disable_segmentation_rendering()
            # Segmentation returns (H, W, 2) geom/object ids — pack to u16.
            if seg_raw.ndim == 3:
                geom_ids = seg_raw[..., 0].astype(np.int32)
                seg = np.where(geom_ids < 0, 0, (geom_ids + 1) & 0xFFFF).astype(np.uint16)
            else:
                seg = np.asarray(seg_raw, dtype=np.uint16)

        color_ref = f"mem://mujoco_egl/color/{sequence}"
        depth_ref = f"mem://mujoco_egl/depth/{sequence}"
        seg_ref = f"mem://mujoco_egl/seg/{sequence}" if seg is not None else None
        self._buffers[color_ref] = color
        self._buffers[depth_ref] = depth
        if seg is not None and seg_ref is not None:
            self._buffers[seg_ref] = seg
        self._last = CaptureBuffers(color_rgb8=color, depth_m_f32=depth, seg_u16=seg)

        return self._channel.wrap_stub_envelope(
            source_timestamp_ns=source_timestamp_ns,
            sequence=sequence,
            scene_revision=scene_revision,
            class_ids=self._class_ids if seg is not None else (),
            color_blob_ref=color_ref,
            depth_blob_ref=depth_ref,
            seg_blob_ref=seg_ref,
        )

    def _free_camera(
        self,
        robot_x: float | None,
        robot_y: float | None,
        robot_yaw_rad: float | None,
    ) -> Any:
        mujoco = self._mujoco
        cam = mujoco.MjvCamera()
        mujoco.mjv_defaultFreeCamera(self._model, cam)

        mount = self._channel.spec.mount
        if robot_x is None or robot_y is None or robot_yaw_rad is None:
            if self._robot_body_id >= 0:
                pos = self._data.xpos[self._robot_body_id]
                robot_x = float(pos[0])
                robot_y = float(pos[1])
                # Approximate yaw from body xmat.
                mat = self._data.xmat[self._robot_body_id].reshape(3, 3)
                robot_yaw_rad = math.atan2(float(mat[1, 0]), float(mat[0, 0]))
            else:
                robot_x = 0.0
                robot_y = 0.0
                robot_yaw_rad = 0.0

        yaw = float(robot_yaw_rad)
        cam_x = float(robot_x) + mount.forward_m * math.cos(yaw) - mount.lateral_m * math.sin(
            yaw
        )
        cam_y = float(robot_y) + mount.forward_m * math.sin(yaw) + mount.lateral_m * math.cos(
            yaw
        )
        cam_z = mount.height_m

        # Free-camera look-at a few meters ahead along yaw, with pitch_up.
        look_dist = 3.0
        pitch = mount.pitch_up_rad
        ahead_x = cam_x + look_dist * math.cos(yaw) * math.cos(pitch)
        ahead_y = cam_y + look_dist * math.sin(yaw) * math.cos(pitch)
        ahead_z = cam_z + look_dist * math.sin(pitch)
        cam.lookat[:] = [ahead_x, ahead_y, ahead_z]
        # Place eye near optical frame by setting distance ≈ look_dist.
        cam.distance = look_dist
        cam.azimuth = math.degrees(yaw) - 90.0
        cam.elevation = -math.degrees(pitch)
        return cam
