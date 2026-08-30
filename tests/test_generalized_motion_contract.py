"""Focused safety contract for simulator-only generalized motion proposals."""

from __future__ import annotations

import dataclasses

import pytest

from parcel_robot.motion.generalized_intent import (
    REVIEWED_CATEGORICAL_ACTIONS,
    GeneralizedMotionContractError,
    LanguageMotionSelectionV1,
    MotionPolicyCandidateV1,
    MotionStateV1,
    MotionTransitionGraphV1,
    MotionTransitionV1,
    ReviewedMotionActionSchemaV1,
    ReviewedMotionCatalogV1,
    ReviewedMotionTargetV1,
    admit_language_selection,
    digest_bytes,
    digest_schema,
)


def _sha(label: str) -> str:
    return digest_bytes(label.encode("ascii"))


def _target(kind: str, target_id: str) -> ReviewedMotionTargetV1:
    return ReviewedMotionTargetV1(
        kind=kind,  # type: ignore[arg-type]
        target_id=target_id,
        review_authority_id="sim-motion-review-board-v1",
        review_evidence_digest=_sha(f"review:{kind}:{target_id}"),
    )


def _catalog(*, add_walk: bool = False) -> ReviewedMotionCatalogV1:
    targets = [
        _target("body", "crouch"),
        _target("body", "lie_down"),
        _target("body", "stand"),
        _target("gait", "crawl"),
        _target("gait", "hold"),
        _target("gait", "run"),
        _target("gait", "trot"),
        _target("style", "alert"),
        _target("style", "calm"),
        _target("style", "playful"),
    ]
    if add_walk:
        targets.append(_target("gait", "walk"))
        targets.sort(key=lambda target: (target.kind, target.target_id))
    return ReviewedMotionCatalogV1(tuple(targets), catalog_id="prototype-sim-v1")


def _edge(kind: str, source: str, target: str) -> MotionTransitionV1:
    return MotionTransitionV1(
        kind=kind,  # type: ignore[arg-type]
        from_target=source,
        to_target=target,
    )


def _graph(catalog: ReviewedMotionCatalogV1) -> MotionTransitionGraphV1:
    edges = (
        _edge("body", "crouch", "lie_down"),
        _edge("body", "crouch", "stand"),
        _edge("body", "lie_down", "crouch"),
        _edge("body", "stand", "crouch"),
        _edge("gait", "crawl", "hold"),
        _edge("gait", "hold", "crawl"),
        _edge("gait", "hold", "trot"),
        _edge("gait", "run", "trot"),
        _edge("gait", "trot", "hold"),
        _edge("gait", "trot", "run"),
        _edge("style", "alert", "calm"),
        _edge("style", "calm", "alert"),
        _edge("style", "calm", "playful"),
        _edge("style", "playful", "calm"),
    )
    return MotionTransitionGraphV1(
        graph_id="prototype-transition-graph-v1",
        reviewed_catalog_digest=catalog.catalog_digest,
        review_evidence_digest=_sha("transition-review"),
        transitions=edges,
    )


def _intent():
    catalog = _catalog()
    graph = _graph(catalog)
    current = MotionStateV1("hold", "calm", "stand")
    selection = LanguageMotionSelectionV1("trot", "alert", "crouch")
    return admit_language_selection(
        selection,
        current=current,
        catalog=catalog,
        transition_graph=graph,
        source_turn_digest=_sha("conversation-turn-17"),
    )


def test_language_surface_is_exactly_three_categorical_targets() -> None:
    selection = LanguageMotionSelectionV1.from_mapping(
        {
            "schema_version": 1,
            "gait_target": "trot",
            "style_target": "calm",
            "body_target": "stand",
        }
    )
    assert selection.as_state() == MotionStateV1("trot", "calm", "stand")

    for forbidden, value in (
        ("latent", [0.2, -0.7]),
        ("joint_targets", {"FL_hip": 1.0}),
        ("torques", [1.0] * 12),
        ("velocity", [0.5, 0.0, 0.0]),
        ("trajectory", [[0.0] * 12]),
    ):
        payload = {
            "schema_version": 1,
            "gait_target": "trot",
            "style_target": "calm",
            "body_target": "stand",
            forbidden: value,
        }
        with pytest.raises(GeneralizedMotionContractError, match="unknown fields"):
            LanguageMotionSelectionV1.from_mapping(payload)


def test_reviewed_catalog_is_immutable_canonical_and_content_bound() -> None:
    catalog = _catalog()
    assert catalog.target("gait", "trot").target_id == "trot"
    assert catalog.catalog_digest == _catalog().catalog_digest
    assert len(catalog.catalog_digest) == 64

    with pytest.raises(GeneralizedMotionContractError, match="sorted"):
        ReviewedMotionCatalogV1(tuple(reversed(catalog.targets)), catalog_id="noncanonical")
    with pytest.raises(GeneralizedMotionContractError, match="unique"):
        ReviewedMotionCatalogV1(
            tuple(
                sorted((*catalog.targets, catalog.targets[0]), key=lambda x: (x.kind, x.target_id))
            ),
            catalog_id="duplicate",
        )


def test_admission_content_binds_reviewed_targets_and_remains_non_authorizing() -> None:
    intent = _intent()
    catalog = _catalog()
    graph = _graph(catalog)

    assert intent.target_state == MotionStateV1("trot", "alert", "crouch")
    assert intent.reviewed_catalog_digest == catalog.catalog_digest
    assert intent.transition_graph_digest == graph.graph_digest
    assert intent.gait_target_digest == catalog.target("gait", "trot").target_digest
    assert intent.style_target_digest == catalog.target("style", "alert").target_digest
    assert intent.body_target_digest == catalog.target("body", "crouch").target_digest
    assert intent.lifecycle == "sim_candidate"
    assert intent.execution_scope == "simulator_only"
    assert intent.physical_commissioned is False
    assert intent.authorizes_motion is False
    assert len(intent.intent_digest) == 64

    for forbidden in (
        "dispatch",
        "execute",
        "authorize",
        "latent",
        "joint_targets",
        "torques",
        "velocity",
    ):
        assert not hasattr(intent, forbidden)
        assert forbidden not in intent.as_dict()


def test_unreviewed_target_and_illegal_transition_are_fail_closed() -> None:
    catalog = _catalog()
    graph = _graph(catalog)
    current = MotionStateV1("hold", "calm", "stand")

    with pytest.raises(GeneralizedMotionContractError, match="not in the reviewed catalog"):
        admit_language_selection(
            LanguageMotionSelectionV1("fly", "calm", "stand"),
            current=current,
            catalog=catalog,
            transition_graph=graph,
            source_turn_digest=_sha("turn"),
        )

    with pytest.raises(GeneralizedMotionContractError, match="not reviewed") as failure:
        admit_language_selection(
            LanguageMotionSelectionV1("run", "calm", "lie_down"),
            current=current,
            catalog=catalog,
            transition_graph=graph,
            source_turn_digest=_sha("turn"),
        )
    assert "gait:hold->run" in str(failure.value)
    assert "body:stand->lie_down" in str(failure.value)


def test_transition_graph_is_directional_and_bound_to_exact_catalog() -> None:
    catalog = _catalog()
    graph = _graph(catalog)
    assert graph.allows("gait", "hold", "trot") is True
    assert graph.allows("gait", "hold", "hold") is True
    assert graph.allows("gait", "hold", "run") is False

    expanded_catalog = _catalog(add_walk=True)
    with pytest.raises(GeneralizedMotionContractError, match="different reviewed catalog"):
        graph.validate_against(expanded_catalog)

    bad_graph = MotionTransitionGraphV1(
        graph_id="bad-endpoint-graph",
        reviewed_catalog_digest=catalog.catalog_digest,
        review_evidence_digest=_sha("bad-graph-review"),
        transitions=(_edge("gait", "hold", "teleport"),),
    )
    with pytest.raises(GeneralizedMotionContractError, match="not in the reviewed catalog"):
        bad_graph.validate_against(catalog)


def test_action_schema_is_derived_categorical_and_refuses_latent_encoding() -> None:
    catalog = _catalog()
    schema = ReviewedMotionActionSchemaV1.from_catalog(catalog)
    schema.validate_against(catalog)

    assert schema.encoding == REVIEWED_CATEGORICAL_ACTIONS
    assert schema.gait_targets == ("crawl", "hold", "run", "trot")
    assert schema.style_targets == ("alert", "calm", "playful")
    assert schema.body_targets == ("crouch", "lie_down", "stand")
    assert "latent" not in schema.as_dict()
    assert "latent_dim" not in schema.as_dict()

    with pytest.raises(GeneralizedMotionContractError, match="latent vectors"):
        dataclasses.replace(schema, encoding="latent_vector")

    changed = ReviewedMotionActionSchemaV1.from_catalog(_catalog(add_walk=True))
    assert changed.action_schema_digest != schema.action_schema_digest


def _candidate(artifact: bytes = b"sim-policy-weights-v1") -> MotionPolicyCandidateV1:
    catalog = _catalog()
    return MotionPolicyCandidateV1(
        candidate_id="terrain-generalist-001",
        policy_artifact_digest=digest_bytes(artifact),
        body_model_digest=_sha("unitree-go2-edu-plus-mjcf-v1"),
        observation_schema_digest=digest_schema(
            {
                "schema": "bounded-sim-observation-v1",
                "fields": ["terrain_class", "slope_band", "contact_mask"],
            }
        ),
        action_schema=ReviewedMotionActionSchemaV1.from_catalog(catalog),
        transition_graph_digest=_graph(catalog).graph_digest,
        controller_frequency_hz=50.0,
        command_envelope_digest=_sha("sim-command-envelope-v1"),
        training_config_digest=_sha("training-config-v1"),
        evaluation_manifest_digest=_sha("held-out-evaluation-manifest-v1"),
        evaluation_evidence_digest=_sha("held-out-evaluation-v1"),
        stop_contract_digest=_sha("sim-stop-contract-v1"),
        fallback_contract_digest=_sha("sim-fallback-contract-v1"),
        termination_contract_digest=_sha("sim-termination-contract-v1"),
    )


def test_policy_candidate_binds_artifact_observation_and_action_schemas() -> None:
    artifact = b"sim-policy-weights-v1"
    candidate = _candidate(artifact)
    candidate.validate_against(catalog=_catalog(), transition_graph=_graph(_catalog()))
    assert candidate.binds_policy_artifact(artifact) is True
    assert candidate.binds_policy_artifact(artifact + b"tampered") is False
    assert candidate.action_schema_digest == candidate.action_schema.action_schema_digest

    changed_observation = dataclasses.replace(
        candidate,
        observation_schema_digest=digest_schema(
            {
                "schema": "bounded-sim-observation-v1",
                "fields": ["terrain_class", "slope_band", "contact_mask", "depth_band"],
            }
        ),
    )
    assert changed_observation.candidate_digest != candidate.candidate_digest

    changed_artifact = _candidate(artifact + b"new")
    assert changed_artifact.candidate_digest != candidate.candidate_digest

    changed_body = dataclasses.replace(candidate, body_model_digest=_sha("other-body"))
    assert changed_body.candidate_digest != candidate.candidate_digest
    changed_fallback = dataclasses.replace(
        candidate, fallback_contract_digest=_sha("other-fallback")
    )
    assert changed_fallback.candidate_digest != candidate.candidate_digest


def test_policy_candidate_binds_mount_critical_control_contracts() -> None:
    candidate = _candidate()
    body = candidate.as_dict()
    assert body["controller_frequency_hz"] == 50.0
    for field in (
        "body_model_digest",
        "command_envelope_digest",
        "evaluation_manifest_digest",
        "evaluation_evidence_digest",
        "stop_contract_digest",
        "fallback_contract_digest",
        "termination_contract_digest",
    ):
        assert isinstance(body[field], str)
        assert len(body[field]) == 64

    for invalid in (True, 0.0, 1_000.1, float("nan"), float("inf")):
        with pytest.raises(GeneralizedMotionContractError, match="controller_frequency_hz"):
            dataclasses.replace(candidate, controller_frequency_hz=invalid)

    other_graph = dataclasses.replace(
        _graph(_catalog()), review_evidence_digest=_sha("other-transition-review")
    )
    with pytest.raises(GeneralizedMotionContractError, match="different transition graph"):
        candidate.validate_against(catalog=_catalog(), transition_graph=other_graph)


@pytest.mark.parametrize(
    ("change", "message"),
    (
        ({"lifecycle": "production"}, "lifecycle"),
        ({"execution_scope": "physical_robot"}, "execution_scope"),
        ({"physical_commissioned": True}, "physical_commissioned"),
        ({"authorizes_motion": True}, "authorizes_motion"),
    ),
)
def test_v1_policy_candidate_cannot_be_promoted_or_physically_commissioned(
    change: dict[str, object], message: str
) -> None:
    with pytest.raises(GeneralizedMotionContractError, match=message):
        dataclasses.replace(_candidate(), **change)


def test_v1_intent_cannot_claim_physical_scope_or_authority() -> None:
    intent = _intent()
    with pytest.raises(GeneralizedMotionContractError, match="physical_commissioned"):
        dataclasses.replace(intent, physical_commissioned=True)
    with pytest.raises(GeneralizedMotionContractError, match="authorizes_motion"):
        dataclasses.replace(intent, authorizes_motion=True)
    with pytest.raises(GeneralizedMotionContractError, match="execution_scope"):
        dataclasses.replace(intent, execution_scope="physical_robot")
