"""Wipe all memory. Useful before recording the demo, so counters start clean.

python -m scripts.reset
python -m scripts.reset --yes    # skip the confirmation
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src import memory  # noqa: E402


def main() -> None:
    before = memory.stats()
    print("current memory:", dict(before))

    if "--yes" not in sys.argv:
        if input("delete all of it? [y/N] ").strip().lower() not in ("y", "yes"):
            print("cancelled")
            return

    with memory.connect() as conn:
        # recall_events and session_steps cascade from their parents.
        conn.execute("DELETE FROM recall_events WHERE true")
        conn.execute("DELETE FROM session_steps WHERE true")
        conn.execute("DELETE FROM sessions WHERE true")
        conn.execute("DELETE FROM lessons WHERE true")
        conn.execute("DELETE FROM incidents WHERE true")

    print("after:", dict(memory.stats()))


if __name__ == "__main__":
    main()
