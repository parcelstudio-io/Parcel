"""Runtime BehaviorChannel adapters wrapping follow/nav/spatial/search/activities."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from parcel_robot.core.resume import ResumeIntent

if TYPE_CHECKING:
    from parcel_robot.core.activities import ActivityCoordinator
    from parcel_robot.navigation.follow import FollowOwnerController
    from parcel_robot.navigation.pipeline import DirectiveNavigator
    from parcel_robot.navigation.search_owner import SearchOwnerController
    from parcel_robot.navigation.spatial import SpatialBehaviorController
    from parcel_robot.runtime import RobotRuntime


class LazyNavigator:
    """Defer ``Dog.navigator`` construction until navigation is actually used."""

    def __init__(self, runtime: RobotRuntime) -> None:
        self._runtime = runtime

    def _get(self) -> Any | None:
        dog = self._runtime.dog
        existing = getattr(dog, "_navigator", None)
        if existing is not None:
            return existing
        if getattr(dog, "navigation_config", None) is None:
            return None
        try:
            return dog.navigator
        except RuntimeError:
            return None

    @property
    def mission(self) -> Any | None:
        nav = self._get()
        return None if nav is None else nav.mission

    @property
    def paused(self) -> bool:
        nav = self._get()
        return False if nav is None else bool(nav.paused)

    def pause(self) -> None:
        nav = self._get()
        if nav is not None:
            nav.pause()

    def resume(self) -> None:
        nav = self._get()
        if nav is not None:
            nav.resume()

    def snapshot(self) -> dict[str, object]:
        nav = self._get()
        if nav is None:
            return {"paused": False, "has_mission": False, "mission_status": None}
        return nav.snapshot()


class FollowChannel:
    name = "follow"
    arbiter_source = "follow"
    priority = 40

    def __init__(
        self,
        controller: FollowOwnerController,
        *,
        on_stop: Callable[[str], None] | None = None,
        on_snapshot: Callable[[], dict[str, object]] | None = None,
    ) -> None:
        self._controller = controller
        self._on_stop = on_stop
        self._on_snapshot = on_snapshot

    def active(self) -> bool:
        return bool(self._controller.enabled)

    def stop(self, reason: str) -> None:
        del reason
        self._controller.stop()
        if self._on_stop is not None:
            self._on_stop("follow")

    def snapshot(self) -> dict[str, object]:
        if self._on_snapshot is not None:
            return self._on_snapshot()
        return self._controller.snapshot()

    def pause(self, reason: str) -> ResumeIntent | None:
        if not self.active():
            return None
        snap = self.snapshot()
        mode = str(snap.get("mode", "direct"))
        distance = snap.get("desired_distance_m")
        intent = ResumeIntent(
            channel="follow",
            payload={
                "mode": mode,
                "distance_m": None if distance is None else float(distance),  # type: ignore[arg-type]
            },
            suspend_reason=reason,
            suspended_at_s=0.0,  # runtime fills via record path
            valid_for_s=120.0,
            requires_fresh_observation=True,
        )
        self._controller.stop()
        if self._on_stop is not None:
            self._on_stop("follow")
        return intent

    def resume(self, intent: ResumeIntent, *, now_s: float) -> None:
        del now_s
        mode = str(intent.payload.get("mode", "direct"))
        distance = intent.payload.get("distance_m")
        if mode == "behind":
            self._controller.start_formation(
                "behind",
                distance_m=None if distance is None else float(distance),  # type: ignore[arg-type]
            )
        else:
            self._controller.start()


class NavigationChannel:
    name = "navigation"
    arbiter_source = "navigation"
    priority = 30

    def __init__(
        self,
        navigator: DirectiveNavigator,
        *,
        is_enabled: Callable[[], bool],
        stop_fn: Callable[[str], None],
        detail_fn: Callable[[], dict[str, object]],
    ) -> None:
        self._navigator = navigator
        self._is_enabled = is_enabled
        self._stop_fn = stop_fn
        self._detail_fn = detail_fn

    def active(self) -> bool:
        return self._is_enabled()

    def stop(self, reason: str) -> None:
        """Hand the caller's reason to the terminal write. Card R12.

        This was ``del reason``. Navigation is the one channel whose stop is
        also a MISSION TERMINAL — a mission-log row, a panel event and a
        narrated sentence, all built from ``reason`` — and throwing the reason
        away here made every one of them read ``navigation_disabled``, the
        detail dataclass's default, whatever had actually ended the mission.
        The owner's emergency stop was the case that made it unacceptable
        (AUDIT_R9_FABLE owner-gated finding 2): a latched e-stop reached the
        log as ``ended (idle): navigation_disabled``.

        The reason is the preempting caller's fact, not this adapter's, so it
        is passed through unaltered — no defaulting, no relabelling. A channel
        that substituted its own word here would be the same defect with a
        better vocabulary.
        """

        self._stop_fn(reason)

    def snapshot(self) -> dict[str, object]:
        detail = dict(self._detail_fn())
        detail.update(self._navigator.snapshot())
        return detail

    def pause(self, reason: str) -> ResumeIntent | None:
        if not self.active() or self._navigator.mission is None:
            return None
        self._navigator.pause()
        return ResumeIntent(
            channel="navigation",
            payload={"directive": self._navigator.mission.directive, "reason": reason},
            suspend_reason=reason,
            suspended_at_s=0.0,
            valid_for_s=300.0,
            requires_fresh_observation=True,
        )

    def resume(self, intent: ResumeIntent, *, now_s: float) -> None:
        del intent, now_s
        self._navigator.resume()


class SpatialChannel:
    name = "spatial"
    arbiter_source = "spatial"
    priority = 50

    def __init__(
        self,
        controller: SpatialBehaviorController,
        *,
        stop_fn: Callable[[str], None],
        detail_fn: Callable[[], dict[str, object]],
    ) -> None:
        self._controller = controller
        self._stop_fn = stop_fn
        self._detail_fn = detail_fn

    def active(self) -> bool:
        return bool(self._controller.active)

    def stop(self, reason: str) -> None:
        self._stop_fn(reason)

    def snapshot(self) -> dict[str, object]:
        return self._detail_fn()

    def pause(self, reason: str) -> ResumeIntent | None:
        del reason
        return None

    def resume(self, intent: ResumeIntent, *, now_s: float) -> None:
        del intent, now_s


class SearchChannel:
    name = "search"
    arbiter_source = "search"
    priority = 35

    def __init__(
        self,
        controller: SearchOwnerController,
        *,
        stop_fn: Callable[[], None],
        detail_fn: Callable[[], dict[str, object]],
        clock: Callable[[], float],
    ) -> None:
        self._controller = controller
        self._stop_fn = stop_fn
        self._detail_fn = detail_fn
        self._clock = clock

    def active(self) -> bool:
        return bool(self._controller.enabled)

    def stop(self, reason: str) -> None:
        del reason
        self._stop_fn()

    def snapshot(self) -> dict[str, object]:
        return self._detail_fn()

    def pause(self, reason: str) -> ResumeIntent | None:
        if not self.active():
            return None
        now = self._clock()
        self._controller.pause(now=now)
        return ResumeIntent(
            channel="search",
            payload={"reason": reason},
            suspend_reason=reason,
            suspended_at_s=now,
            valid_for_s=120.0,
            requires_fresh_observation=False,
        )

    def resume(self, intent: ResumeIntent, *, now_s: float) -> None:
        del intent
        self._controller.resume(now=now_s)


class ActivitiesChannel:
    name = "activities"
    arbiter_source = "voice"
    priority = 55

    def __init__(self, coordinator: ActivityCoordinator) -> None:
        self._coordinator = coordinator

    def active(self) -> bool:
        snap = self._coordinator.snapshot()
        running = snap.get("running")
        return bool(running)

    def stop(self, reason: str) -> None:
        self._coordinator.clear(reason)

    def snapshot(self) -> dict[str, object]:
        return dict(self._coordinator.snapshot())

    def pause(self, reason: str) -> ResumeIntent | None:
        del reason
        return None

    def resume(self, intent: ResumeIntent, *, now_s: float) -> None:
        del intent, now_s


__all__ = [
    "ActivitiesChannel",
    "FollowChannel",
    "LazyNavigator",
    "NavigationChannel",
    "SearchChannel",
    "SpatialChannel",
]
