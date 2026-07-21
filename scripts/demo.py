"""End-to-end demo from the terminal. Good material for the submission video.

    python -m scripts.demo
    python -m scripts.demo "your own alert text here"
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src import agent, memory  # noqa: E402

DEFAULT_ALERT = (
    "PagerDuty SEV1: orders-api p99 latency went from 200ms to 25s in the last "
    "15 minutes. Roughly a third of POST /orders are timing out at the gateway. "
    "Host CPU and memory are flat. Database CPU looks normal. We shipped a "
    "retry wrapper to this service nine days ago."
)


def main() -> None:
    alert = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ALERT

    print("=" * 78)
    print("MEMORY BEFORE:", memory.stats())
    print("=" * 78)
    print(f"\nALERT\n-----\n{alert}\n")

    result = agent.handle_alert(alert)

    print("TOOLS THE AGENT CALLED")
    print("----------------------")
    for name in result["tools_used"]:
        print(f"  - {name}")

    print("\nANSWER")
    print("------")
    print(result["answer"])

    print("\n" + "=" * 78)
    print("MEMORY AFTER: ", memory.stats())
    print(f"session id:    {result['session_id']}")
    print("Replay it any time with memory.get_session(session_id) -- the whole")
    print("reasoning trace is durable in CockroachDB, not in process memory.")
    print("=" * 78)


if __name__ == "__main__":
    main()
