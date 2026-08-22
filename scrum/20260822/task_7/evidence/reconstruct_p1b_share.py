"""Reconstruct 'the file without card P1-B' by reverse-applying my patches."""
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/jaewoo-jang/Desktop/Projects/Parcel")
HERE = Path("/home/jaewoo-jang/.cache/parcel-p1b")

# (target, [tag, ...]) in APPLICATION order; reversed below.
PLAN = {
    "src/parcel_robot/runtime.py": [
        "S", "T", "U", "V", "W", "X", "Y", "Z", "AG", "AH", "AP", "AQ", "AR",
        "B3", "B4", "B5", "B6", "B7", "BQ"],
    "src/parcel_robot/camera_channel/ingress.py": [
        "v", "w", "x", "y", "z", "A", "B", "C", "D", "E", "F", "G", "H", "I",
        "J", "K", "L", "M", "N", "O", "P", "Q", "R"],
    "src/parcel_robot/online_map/store.py": ["d", "e", "f", "B1"],
    "src/parcel_robot/online_map/online_map.py": ["g", "h", "i", "j", "k", "B2"],
    "configs/navigation/prototype.yaml": ["AA", "AS", "BR"],
    "tests/test_c3_cutover.py": ["AC", "AD"],
    "tests/test_r24_lock_discipline.py": ["AU", "AV", "AW"],
    # AB's original payload carried its surrounding context, and card P1-D has
    # since inserted a line into that context — so the reverse-apply is keyed on
    # P1-B's OWN six lines instead. Concurrent writers are the normal case in
    # this wave; an attribution method that breaks when a neighbour edits the
    # same file is not an attribution method.
    "tests/test_p0d_navigation_unblocks.py": ["AB2"],
}

def main() -> int:
    out_root = HERE / "baseline"
    if out_root.exists():
        shutil.rmtree(out_root)
    rows = []
    for relative, tags in PLAN.items():
        target = REPO / relative
        text = target.read_text(encoding="utf-8")
        for tag in reversed(tags):
            old = (HERE / f"old{tag}.txt").read_text(encoding="utf-8")
            new = (HERE / f"new{tag}.txt").read_text(encoding="utf-8")
            n = text.count(new)
            if n != 1:
                print(f"  !! {relative}: reverse tag {tag} matched {n} times")
                return 2
            text = text.replace(new, old)
        dest = out_root / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        ns = subprocess.run(
            ["git", "diff", "--no-index", "--numstat", str(dest), str(target)],
            capture_output=True, text=True, check=False).stdout.strip()
        add, rem = (ns.split()[0], ns.split()[1]) if ns else ("0", "0")
        rows.append((relative, add, rem))
        total = subprocess.run(
            ["git", "diff", "--numstat", "--", relative], cwd=str(REPO),
            capture_output=True, text=True, check=False).stdout.strip()
        t = total.split() if total else ["0", "0"]
        print(f"{relative:50s}  P1-B +{add:>4}/-{rem:<3}   file total +{t[0]}/-{t[1]}")
    return 0

sys.exit(main())
