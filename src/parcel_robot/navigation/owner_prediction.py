"""Deterministic constant-velocity prediction for an observed owner."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PredictedPath:
    horizon_s: float
    step_s: float
    points: tuple[tuple[float, float], ...]
    speed_mps: float
    heading_rad: float
    confidence: float


class OwnerMotionPredictor:
    """Small CV Kalman filter with acceleration process noise.

    A fading-memory covariance boost makes the CV estimate responsive to turns
    while retaining the lower-noise steady-state behavior of a CV model.
    """

    _MEASUREMENT_STD_M = 0.04
    _STALE_S = 1.5
    _NIS_WINDOW = 10

    def __init__(
        self,
        *,
        horizon_s: float = 2.5,
        step_s: float = 0.1,
        process_accel_std: float = 0.8,
    ) -> None:
        self._validate_positive(horizon_s, "horizon_s")
        self._validate_positive(step_s, "step_s")
        self._validate_positive(process_accel_std, "process_accel_std")
        self.horizon_s = float(horizon_s)
        self.step_s = float(step_s)
        self.process_accel_std = float(process_accel_std)
        self.reset()

    @staticmethod
    def _validate_positive(value: float, name: str) -> None:
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"{name} must be finite and positive")

    @staticmethod
    def _validate_finite(value: float, name: str) -> float:
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
        return value

    def reset(self) -> None:
        self._state: np.ndarray | None = None
        self._covariance: np.ndarray | None = None
        self._state_time_s: float | None = None
        self._last_observation_s: float | None = None
        self._last_call_s: float | None = None
        self._nis_values: deque[float] = deque(maxlen=self._NIS_WINDOW)

    @property
    def nis(self) -> float:
        if not self._nis_values:
            return 0.0
        return float(sum(self._nis_values) / len(self._nis_values))

    def _transition(self, dt_s: float) -> tuple[np.ndarray, np.ndarray]:
        transition = np.array(
            ((1.0, 0.0, dt_s, 0.0), (0.0, 1.0, 0.0, dt_s),
             (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0)),
            dtype=float,
        )
        dt2 = dt_s * dt_s
        process_map = np.array(
            ((0.5 * dt2, 0.0), (0.0, 0.5 * dt2), (dt_s, 0.0), (0.0, dt_s)),
            dtype=float,
        )
        process = (self.process_accel_std**2) * (process_map @ process_map.T)
        return transition, process

    def _advance(self, now_s: float) -> None:
        if self._state is None or self._state_time_s is None:
            return
        dt_s = now_s - self._state_time_s
        if dt_s <= 0.0:
            return
        transition, process = self._transition(dt_s)
        self._state = transition @ self._state
        assert self._covariance is not None
        self._covariance = transition @ self._covariance @ transition.T + process
        self._state_time_s = now_s

    def _projected_state(
        self, now_s: float
    ) -> tuple[np.ndarray, np.ndarray, float] | None:
        """Return (state, covariance, time) advanced to ``now_s`` without mutation."""

        if self._state is None or self._covariance is None or self._state_time_s is None:
            return None
        dt_s = now_s - self._state_time_s
        if dt_s <= 0.0:
            return self._state.copy(), self._covariance.copy(), self._state_time_s
        transition, process = self._transition(dt_s)
        state = transition @ self._state
        covariance = transition @ self._covariance @ transition.T + process
        return state, covariance, now_s

    def observe(
        self,
        x: float,
        y: float,
        *,
        now_s: float,
        visible: bool = True,
    ) -> None:
        x = self._validate_finite(x, "x")
        y = self._validate_finite(y, "y")
        now_s = self._validate_finite(now_s, "now_s")
        if self._last_call_s is not None and now_s + 1e-12 < self._last_call_s:
            raise ValueError("now_s must be monotonic")
        self._last_call_s = max(now_s, self._last_call_s or now_s)
        if not visible:
            return

        measurement = np.array((x, y), dtype=float)
        if self._state is None:
            self._state = np.array((x, y, 0.0, 0.0), dtype=float)
            self._covariance = np.diag((0.04**2, 0.04**2, 2.0**2, 2.0**2))
            self._state_time_s = now_s
            self._last_observation_s = now_s
            return

        self._advance(now_s)
        assert self._covariance is not None
        observation = np.array(((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0)))
        noise = np.eye(2) * self._MEASUREMENT_STD_M**2
        innovation = measurement - observation @ self._state
        innovation_cov = observation @ self._covariance @ observation.T + noise
        nis = float(innovation @ np.linalg.solve(innovation_cov, innovation))
        self._nis_values.append(min(nis, 1_000.0))

        # Hot innovations indicate a turn or a bad track. Inflate velocity
        # uncertainty so subsequent genuine observations can redirect quickly.
        if nis > 9.21:
            self._covariance[2:, 2:] *= min(12.0, 1.0 + nis / 9.21)
            innovation_cov = observation @ self._covariance @ observation.T + noise

        gain = np.linalg.solve(innovation_cov, observation @ self._covariance).T
        self._state = self._state + gain @ innovation
        identity = np.eye(4)
        residual_map = identity - gain @ observation
        self._covariance = residual_map @ self._covariance @ residual_map.T + gain @ noise @ gain.T
        self._last_observation_s = now_s

    def predict(self, *, now_s: float) -> PredictedPath | None:
        now_s = self._validate_finite(now_s, "now_s")
        if self._last_call_s is not None and now_s + 1e-12 < self._last_call_s:
            raise ValueError("now_s must be monotonic")
        self._last_call_s = max(now_s, self._last_call_s or now_s)
        if self._state is None or self._last_observation_s is None:
            return None
        if now_s - self._last_observation_s > self._STALE_S:
            return None

        # Predict must not commit process noise: different call cadences would
        # otherwise retune the filter (arbitration 2026-08-04). Observe owns
        # the only state writes.
        projected = self._projected_state(now_s)
        if projected is None:
            return None
        state, _covariance, _time = projected
        x, y, vx, vy = (float(value) for value in state)
        count = round(self.horizon_s / self.step_s)
        points = tuple(
            (x + vx * self.step_s * index, y + vy * self.step_s * index)
            for index in range(1, count + 1)
        )
        speed = math.hypot(vx, vy)
        heading = math.atan2(vy, vx) if speed > 1e-9 else 0.0
        # Two-dimensional consistent innovations have expected NIS ~= 2.
        confidence = math.exp(-0.12 * max(0.0, self.nis - 2.0))
        return PredictedPath(
            horizon_s=self.horizon_s,
            step_s=self.step_s,
            points=points,
            speed_mps=speed,
            heading_rad=heading,
            confidence=max(0.0, min(1.0, confidence)),
        )
