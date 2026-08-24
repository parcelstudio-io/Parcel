#!/usr/bin/env python3
"""Smoke-test city navigation: ground a directive, walk stub city with pedestrians."""

from __future__ import annotations

from parcel_robot.navigation.base import NavObservation
from parcel_robot.navigation.envs.metaurban_env import MetaUrbanNavEnv
from parcel_robot.navigation.pipeline import DirectiveNavigator


def main() -> None:
    nav = DirectiveNavigator.from_config("configs/navigation/default.yaml")
    print("models:", [m.id for m in nav.list_models()])
    mission = nav.parse("I want you to go to the coffee shop at 42nd street")
    print(f"grounded → {mission.goal.poi_id} @ ({mission.goal.x:.1f}, {mission.goal.y:.1f})")

    env = MetaUrbanNavEnv(navigator=nav, density_ped=1.0, density_obj=0.4, seed=0)
    obs, info = env.reset(options={"directive": mission.directive})
    print("reset obs:", obs.round(2), "goal:", info["goal"].label)

    for step in range(80):
        obs, reward, terminated, truncated, info = env.step([0.0, 0.0, 0.0])
        if step % 20 == 0 or terminated or truncated:
            print(
                f"t={step:03d} dist={info['dist_to_goal']:.2f} "
                f"R={reward:.2f} arrived={info['arrived']} collided={info['collided']}"
            )
        if terminated or truncated:
            break
    env.close()

    # Direct Dog-style mid-level step without env
    nav2 = DirectiveNavigator.from_config()
    nav2.start("go to the bookstore")
    cmd = nav2.step(
        NavObservation(position=(0.0, 0.0, 0.0), heading_deg=0.0, nearest_person_m=3.0)
    )
    print("bookstore cmd:", cmd)
    nav2.close()


if __name__ == "__main__":
    main()
