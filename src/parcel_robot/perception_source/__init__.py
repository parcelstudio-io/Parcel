"""Card C-3 — where semantic candidates come from, and the shadow instrument.

``selection`` owns the axis (``oracle`` / ``learned_map`` / ``shadow``) and every
implication of it, including whether the ``demo_pois.yaml`` POI arm may load.
``shadow`` owns the divergence taxonomy, its two denominators, and the
frames-attached evidence rows.

Deliberately NOT here: the noise ladder (``detection_adapter.perception_chain``,
``perception.tier``) and the abstention gate (``perception_abstention``, PG-3).
Those are separate axes owned by other cards; this package selects a source and
consumes their verdicts, it does not fork either.
"""
