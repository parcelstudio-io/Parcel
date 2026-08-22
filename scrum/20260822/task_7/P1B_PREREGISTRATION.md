# P1-B — pre-registration (written BEFORE any measurement)

**Card:** `README.md` · **Board:** `../TASK_BOARD.md` · **Executor:** Claude Opus
**Written:** 2026-08-22, before the first source edit of this card and before any
number below was measured. Priors are MOVE-1's three completed `city_block`
patrol runs (`scrum/20260821/task_20/evidence/patrol_city_block_*/summary.json`),
read read-only: 13 / 51 / 57 entries, 37–42 frames, 267–331 detections in a
120 s budget, and **`relief_unverified` on 100 % of entries in all three**.

A miss is recorded as a miss. Nothing below is re-cut after measuring.

## Acceptance rows

| # | Row | Pre-registered bound |
|---|---|---|
| **R-1** | Dev-scene entry count: one 120 s patrol on `city_block` with the runtime's OWN map writer under `perception.semantic_source: shadow` | `10 ≤ active entries ≤ 90` and `≥ 3` distinct labels |
| **R-2** | Real embeddings: fraction of active entries whose `embedding_stamp` is non-`None`, `dim == 768`, `model_id` naming SigLIP-2 | `≥ 0.90` |
| **R-3** | Measured relief: fraction of active entries with `relief_m is not None` and `hygiene_note != "relief_unverified"` | `≥ 0.50` (prior: **0.00**) |
| **R-4** | Persistence round-trip: reload the persisted store in a FRESH process | `len(reloaded) == len(persisted)` and `as_dict()` equal for **every** entry, including `thumbnail` and `provenance.origin` — 100 %, no exceptions |
| **R-5** | Thumbnails survive persistence (AU-C2-1) | `≥ 0.50` of active entries carry non-empty thumbnail bytes after reload, **byte-identical** to before |
| **R-6** | Query-union overflow (D-R2) is bounded and LOUD | a 20-phrase request yields a batch of `≤ 16` including `person`, `poll_once` returns a frame (not `None`), and the drop is counted in ingress stats |
| **R-7** | A store mixing `EvidenceOrigin.PHYSICAL` and `SIMULATION` entries is refused at load | refusal raised, message names both origins |
| **R-8** | Flag-off identity: with `semantic_source` absent (oracle) the runtime builds no map, installs no learned map, and persists nothing | `active_learned_map() is None`, no store file created |
| **R-9** | D-R1: the configured `perception.camera_ingress_queries` batch is pinned INSIDE the ingress, not only re-supplied by the directive path | `ingress.pinned_queries == tuple(config.queries)` after `_attach_configured_camera_ingress` |

## Seeded-RED guards (each: seed, fail, restore byte-identically, purge `__pycache__`, rerun)

| # | Seed |
|---|---|
| **S-1** | `MapEntry.as_dict` drops `thumbnail` again (AU-C2-1's exact defect) |
| **S-2** | `OnlineMapStore.load_all` stops checking origin mixing |
| **S-3** | `observation_from_record` accepts an embedding with no stamp |
| **S-4** | the query-batch cap is removed (D-R2 fail-silent blindness returns) |
| **S-5** | the attach site stops setting `ingress.pinned_queries` (D-R1) |
| **S-6** | the attach site stops setting `ingress.embed_fn` (entries fall back to the 8-dim label hash) |
| **S-7** | the runtime stops persisting the map on `close()` |

## What is deliberately NOT claimed

* No camera. Every number is MuJoCo `city_block`, `EvidenceOrigin.SIMULATION`.
  The `PHYSICAL` arm is exercised only by construction, never by a sensor.
* Retrieval quality is not measured here. This card makes the map *writable,
  embedded, relief-measured and reloadable*; whether the embeddings retrieve
  better than the label hash is a bench P1-D/C-2 owns.
