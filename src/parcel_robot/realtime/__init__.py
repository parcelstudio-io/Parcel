"""OpenAI Realtime conversational lane — R1 slice (fake-first, offline).

R1 is deliberately small and entirely credential-free. Everything here runs
against :class:`~parcel_robot.realtime.fake_server.FakeRealtimeServer` over an
in-process transport pair; the live WebSocket transport is R1.5 and is a new
implementation of :class:`~parcel_robot.realtime.transport.Transport`, not an
edit to the lane.

Flag-off is *file absent*: with no ``configs/realtime.yaml`` the lane is not
constructed and the runtime boots byte-identically.
"""
