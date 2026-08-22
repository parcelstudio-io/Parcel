# Task 18 — NM-1: a promotion gate that tests correctness, not consistency

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 standing rules apply). **Evidence:** P1-D's row 5 MISS
(`task_9/P1D_STATUS.md` §3, §7 risk 3): the k-consistency gate promoted
"yellow cylinder" for a bollard and "pole" for a traffic light after three
agreeing visits at full resolution (2 of 2 false promotions); the shipping
path shows 0 only because 64-px thumbnails are too unstable to reach k —
"safe because blind". Naming accuracy measured 45.0% on 40 crops vs the
research's 82–87% prediction (cutover_research, decision 5).

## Why
k-consistency was the research's answer to ~1-in-7 wrong names; the measured
rate is closer to 1-in-2, and a VLM that is consistently wrong sails through
a consistency filter. Vocabulary growth is the "learn about the world"
directive mechanized — it must not mechanize confident mistakes into
`known_places()`.

## Work
1. **Measure why 45%:** crop resolution (64 px vs full), prompt, class
   distribution — pre-register the three arms, run them on the same 40
   crops, report. If full-res crops recover the predicted accuracy, the
   thumbnail size (P1-B's bounded crop) is the lever and the card says so.
2. **Add a correctness signal to promotion:** a proposed name promotes only
   when (a) k independent visits agree AND (b) the open-vocabulary detector
   (OWLv2 / OmDet seat) fires on the proposed name over the entry's best
   view with label strength above a pre-registered floor — the detector is
   an independent judge the VLM cannot collude with. Names that fail (b)
   stay `vlm_proposed` forever and never enter `known_places()`.
3. Re-run P1-D's full-res arm: the bollard and the traffic light must NOT
   promote; pre-register the false-promotion bound (0) and the true-promotion
   recall on the 40-crop fixture.
4. Seeds RED: promotion without the detector agreement; the floor lowered
   to pass.

OWNS: `online_map/naming.py`, `vlm_veto/` prompt/crop handling,
`configs/navigation/prototype.yaml` naming keys, `tests/test_nm1_*.py`,
`task_18/` docs. MUST NOT TOUCH: `online_map/` beyond `naming.py` (P1-B),
`perception_abstention.py` roster, `ingress.py`.

## Definition of done
Three-arm accuracy measurement reported; 0 false promotions on the full-res
arm with recall reported; seeds RED; `NM1_STATUS.md`.
