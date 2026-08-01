from parcel_robot.agent import VoiceAgent
from parcel_robot.models import Pose, ToolCall, VelocityCommand
from parcel_robot.motion import MotionRouter, RLPolicyBackend, SportMoveBackend, build_motion_router
from parcel_robot.safety import SafetySupervisor


def _router(**hooks):
    return MotionRouter(
        backends={
            "sport": SportMoveBackend(enabled=False),
            "rl": RLPolicyBackend(policy_path=""),
        },
        active="rl",
        **hooks,
    )


def test_walk_forward_uses_rl_backend():
    walks = []
    router = _router(on_command=walks.append)
    agent = VoiceAgent({}, [], lambda pose: None, motion=router)

    assert agent.handle_text("walk forward") == "Walking forward."
    assert walks == [VelocityCommand(vx=0.3, vy=0.0, vyaw=0.0)]
    assert "rl" in router.status()


def test_switch_backend_and_sport_stub():
    router = _router()
    agent = VoiceAgent({}, [], lambda pose: None, motion=router)

    assert "sport" in agent.handle_text("use sport backend")
    assert agent.handle_text("walk forward") == "Walking forward."
    assert router.active == "sport"
    sport = router.backends["sport"]
    assert isinstance(sport, SportMoveBackend)
    assert sport.history[-1].vx == 0.3
    assert "Sport Move armed (stub)" in sport.start(VelocityCommand(vx=0.0))


def test_pose_stops_active_walk():
    events = []
    router = _router(on_command=lambda cmd: events.append(("walk", cmd)), on_stop=lambda: events.append("stop"))
    pose = Pose("sit", {"FL_hip_joint": 0.0})
    sent = []
    agent = VoiceAgent({"sit": pose}, [], sent.append, motion=router)

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
            "backend": "sport",
            "sport": {"enabled": False, "interface": "lo", "domain_id": 1},
            "rl": {"policy_path": ""},
        }
    )
    assert router.active == "sport"
    assert router.walk(VelocityCommand(vx=0.1)).startswith("Sport Move armed")
