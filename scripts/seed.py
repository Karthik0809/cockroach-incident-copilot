"""Seed long-term memory with historical incidents.

Each incident is embedded through Bedrock and written with its vector in one
transaction, along with the lesson distilled from it.

    python -m scripts.seed
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src import memory  # noqa: E402

DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "incidents.json"


def main() -> None:
    incidents = json.loads(DATA.read_text(encoding="utf-8"))
    print(f"seeding {len(incidents)} incidents ...")

    for record in incidents:
        lesson = record.pop("lesson", None)
        incident_id = memory.remember_incident(**record)
        if lesson:
            # Seeded lessons start well-trusted; they came from real postmortems.
            memory.remember_lesson(incident_id, lesson, confidence=0.75)
        print(f"  + {record['external_id']}  {record['title']}")

    print("done:", memory.stats())


if __name__ == "__main__":
    main()
