from pathlib import Path

from commissioned_sim import commissioned_agent_kwargs

from parcel_robot.models import ToolCall, VelocityCommand
from parcel_robot.motion.router import (
    MotionRouter,
    RLPolicyBackend,
    VendorVelocityBackend,
    build_motion_router,
)
from parcel_robot.safety import SafetySupervisor
from parcel_robot.skills.api import Dog
from parcel_robot.voice.agent import VoiceAgent

REPO = Path(__file__).resolve().parents[1]
ROBOT_CONFIG = REPO / "configs" / "robot.yaml"


def _router(**hooks):
    return MotionRouter(
        backends={
            "vendor": VendorVelocityBackend(enabled=False),
            "rl": RLPolicyBackend(policy_path=""),
        },
        active="rl",
        **hooks,
    )


def test_walk_forward_uses_rl_backend():
    walks = []
    router = _router(on_command=walks.append)
    agent = VoiceAgent(
        {},
        [],
        lambda pose: None,
        motion=router,
        **commissioned_agent_kwargs(ROBOT_CONFIG, include_embodied=False),
    )

    assert agent.handle_text("walk forward") == "Walking forward."
    assert walks == [VelocityCommand(vx=0.3, vy=0.0, vyaw=0.0)]
    assert "rl" in router.status()


def test_switch_backend_and_vendor_stub():
    router = _router()
    agent = VoiceAgent(
        {},
        [],
        lambda pose: None,
        motion=router,
        **commissioned_agent_kwargs(ROBOT_CONFIG, include_embodied=False),
    )

    assert "vendor" in agent.handle_text("use vendor backend")
    assert agent.handle_text("walk forward") == "Walking forward."
    assert router.active == "vendor"
    vendor = router.backends["vendor"]
    assert isinstance(vendor, VendorVelocityBackend)
    assert vendor.history[-1].vx == 0.3
    assert "Vendor velocity armed (stub)" in vendor.start(VelocityCommand(vx=0.0))


def test_legacy_sport_alias_switches_to_vendor_backend():
    router = _router()
    agent = VoiceAgent(
        {},
        [],
        lambda pose: None,
        motion=router,
        **commissioned_agent_kwargs(ROBOT_CONFIG, include_embodied=False),
    )

    assert "vendor" in agent.handle_text("use sport backend")
    assert router.active == "vendor"


def test_pose_stops_active_walk():
    events = []
    router = _router(
        on_command=lambda cmd: events.append(("walk", cmd)), on_stop=lambda: events.append("stop")
    )
    sent = []
    dog = Dog.from_config(ROBOT_CONFIG, motion=router, on_pose=sent.append)
    pose = dog.poses()["sit"]
    agent = VoiceAgent(
        dog.poses(),
        [],
        sent.append,
        motion=router,
        dog=dog,
        **commissioned_agent_kwargs(ROBOT_CONFIG),
    )

    agent.handle_text("walk forward")
    agent.handle_text("do the sit pose")

    assert events[0][0] == "walk"
    assert "stop" in events
    assert sent == [pose]


def test_safety_rejects_overlimit_velocity():
    supervisor = SafetySupervisor({})
    result = supervisor.validate(ToolCall("set_velocity", {"vx": 9.0}))
    assert not result.accepted


def test_build_motion_router_from_config():
    router = build_motion_router(
        {
            "backend": "vendor",
            "vendor": {"enabled": False},
            "rl": {"policy_path": ""},
        }
    )
    assert router.active == "vendor"
    assert router.walk(VelocityCommand(vx=0.1)).startswith("Vendor velocity armed")


def test_build_motion_router_accepts_legacy_sport_config():
    router = build_motion_router(
        {
            "backend": "sport",
            "sport": {"enabled": False, "interface": "lo", "domain_id": 1},
            "rl": {"policy_path": ""},
        }
    )
    assert router.active == "vendor"
    assert router.walk(VelocityCommand(vx=0.1)).startswith("Vendor velocity armed")
