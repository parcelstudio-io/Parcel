from __future__ import annotations

import argparse
from pathlib import Path

from .sim_ipc import DEFAULT_SOCKET
from .skills.api import Dog

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "configs" / "robot.yaml"
FALLBACK_CONFIG = Path(__file__).with_name("config") / "robot.yaml"

try:
    import tkinter as tk

    _HAS_TK = True
except ModuleNotFoundError:
    tk = None  # type: ignore[assignment]
    _HAS_TK = False


class ControlPanel:
    """Compact button pad that executes Dog catalog skills over the sim socket."""

    def __init__(self, config_path: Path, socket_path: Path):
        if not _HAS_TK:
            raise RuntimeError(
                "tkinter is unavailable. Install system package python3-tk "
                "(e.g. sudo apt install python3-tk), or use --cli."
            )
        self.dog = Dog.from_config(config_path, sim_socket=str(socket_path))
        self.root = tk.Tk()
        self.root.title("Parcel controls")
        self.root.resizable(False, False)
        self.status = tk.StringVar(value="Ready — start parcel-sim first")
        self._build()

    def _send(self, skill_id: str, **overrides: float) -> None:
        try:
            result = self.dog.execute(skill_id, **overrides)
        except (ConnectionRefusedError, FileNotFoundError, OSError, KeyError) as error:
            self.status.set(f"Failed: {error}")
            return
        self.status.set(result.message if result.accepted else f"Rejected: {result.message}")

    def _stop(self) -> None:
        try:
            result = self.dog.stop()
        except (ConnectionRefusedError, FileNotFoundError, OSError) as error:
            self.status.set(f"Failed: {error}")
            return
        self.status.set(result.message)

    def _build(self) -> None:
        frame = tk.Frame(self.root, padx=12, pady=12)
        frame.grid(row=0, column=0)

        tk.Label(frame, text="Locomotion", font=("Sans", 11, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 6)
        )
        loco = [
            ("Forward", "walk_forward"),
            ("Back", "walk_backward"),
            ("Left", "strafe_left"),
            ("Right", "strafe_right"),
            ("Turn ◀", "turn_left"),
            ("Turn ▶", "turn_right"),
            ("Trot", "trot"),
            ("Run", "run"),
            ("Crawl", "crawl"),
        ]
        for index, (label, skill_id) in enumerate(loco):
            tk.Button(
                frame,
                text=label,
                width=10,
                command=lambda sid=skill_id: self._send(sid),
            ).grid(row=1 + index // 3, column=index % 3, padx=4, pady=4)
        tk.Button(frame, text="Stop", width=10, command=self._stop).grid(
            row=4, column=1, padx=4, pady=4
        )

        tk.Label(frame, text="Skills", font=("Sans", 11, "bold")).grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(12, 6)
        )
        skills = [
            skill
            for skill in self.dog.list_skills()
            if skill.kind in {"pose", "trajectory"}
        ]
        for index, skill in enumerate(skills):
            tk.Button(
                frame,
                text=skill.id,
                width=10,
                command=lambda sid=skill.id: self._send(sid),
            ).grid(row=6 + index // 3, column=index % 3, padx=4, pady=4)

        tk.Label(frame, textvariable=self.status, fg="#444").grid(
            row=40, column=0, columnspan=3, sticky="w", pady=(12, 0)
        )
        tk.Label(
            frame,
            text="Viewer keys: W/S A/D Q/E Space · 1/2 poses",
            fg="#666",
        ).grid(row=41, column=0, columnspan=3, sticky="w", pady=(4, 0))

    def run(self) -> None:
        self.root.mainloop()


def run_cli_panel(config_path: Path, socket_path: Path) -> None:
    """Terminal menu when tkinter/GUI is unavailable."""
    dog = Dog.from_config(config_path, sim_socket=str(socket_path))
    options = [
        ("walk_forward", "Walk forward"),
        ("walk_backward", "Walk backward"),
        ("strafe_left", "Strafe left"),
        ("strafe_right", "Strafe right"),
        ("turn_left", "Turn left"),
        ("turn_right", "Turn right"),
        ("trot", "Trot"),
        ("run", "Run"),
        ("crawl", "Crawl"),
        ("sit", "Sit"),
        ("bow", "Bow"),
        ("jump", "Jump"),
        ("kick_front", "Kick front"),
        ("stand", "Stand"),
    ]
    print("Parcel CLI controls (no tkinter). Type number or skill id, 'stop', or 'q'.")
    while True:
        print()
        for index, (skill_id, label) in enumerate(options, start=1):
            print(f"  {index:2d}. {label} ({skill_id})")
        print("   s. stop")
        print("   q. quit")
        choice = input("> ").strip().lower()
        if choice in {"q", "quit", "exit"}:
            dog.stop()
            return
        if choice in {"s", "stop"}:
            print(dog.stop().message)
            continue
        skill_id = None
        if choice.isdigit():
            index = int(choice) - 1
            if 0 <= index < len(options):
                skill_id = options[index][0]
        elif choice in dog.catalog.ids():
            skill_id = choice
        if skill_id is None:
            print("Unknown choice")
            continue
        try:
            result = dog.execute(skill_id)
            print(result.message)
        except (ConnectionRefusedError, FileNotFoundError, OSError) as error:
            print(f"Sim not connected: {error}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Button panel for parcel-sim")
    default_config = DEFAULT_CONFIG if DEFAULT_CONFIG.is_file() else FALLBACK_CONFIG
    parser.add_argument("--config", default=str(default_config))
    parser.add_argument("--socket", default=str(DEFAULT_SOCKET))
    parser.add_argument(
        "--cli",
        action="store_true",
        help="use a terminal menu instead of the Tk button window",
    )
    args = parser.parse_args()
    config_path = Path(args.config)
    socket_path = Path(args.socket)
    if args.cli or not _HAS_TK:
        if not _HAS_TK and not args.cli:
            print(
                "tkinter not found; falling back to CLI controls. "
                "Install with: sudo apt install python3-tk"
            )
        run_cli_panel(config_path, socket_path)
        return
    ControlPanel(config_path, socket_path).run()


if __name__ == "__main__":
    main()
