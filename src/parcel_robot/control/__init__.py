"""Vendor-neutral locomotion control above the sole-writer gateway.

Normal runtime factories expose simulator, disarmed-gateway, and explicitly
commissioned-gateway managers.  The retired in-process ``unitree_sport``
builder always refuses and is not registered.  Unitree SDK2 belongs to the
separate ``parcel-gateway`` process; this package reaches it only through the
typed Unix client.

The standalone Unitree commissioning builders are deliberately outside the
runtime registry.  Their armed CLI is mutually exclusive with the gateway and
must hold the same device-wide writer lock for the life of its SDK process.
"""
