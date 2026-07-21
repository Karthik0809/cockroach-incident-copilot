"""Create the schema. Run once against a fresh CockroachDB cluster.

python -m scripts.init_db
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src import memory  # noqa: E402

SCHEMA = pathlib.Path(__file__).resolve().parents[1] / "schema" / "001_schema.sql"


def main() -> None:
    print(f"applying {SCHEMA.name} ...")
    memory.init_schema(str(SCHEMA))
    print("schema ready:", memory.stats())


if __name__ == "__main__":
    main()
