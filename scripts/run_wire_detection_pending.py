import sys
import time

sys.path.append('/app')

from orchestration.continuous_processor import (  # pylint: disable=wrong-import-position
    WorkQueue,
    process_wire_detection,
    ENABLE_WIRE_DETECTION,
    WIRE_DETECTION_BATCH_SIZE,
)


def main() -> None:
    if not ENABLE_WIRE_DETECTION:
        print("Wire detection is disabled via environment flag; aborting.", flush=True)
        return

    iteration = 0
    idle_loops = 0

    while True:
        iteration += 1
        counts = WorkQueue.get_counts()
        pending = counts.get("wire_detection_pending", 0) or 0

        print(f"Iteration {iteration}: pending={pending}", flush=True)
        if pending == 0:
            print("No pending articles remain for wire detection.", flush=True)
            break

        batch = max(1, min(pending, WIRE_DETECTION_BATCH_SIZE))
        processed = process_wire_detection(batch)
        if processed:
            idle_loops = 0
            print(f"Processed batch of up to {batch}; sleeping 1s", flush=True)
            time.sleep(1)
        else:
            idle_loops += 1
            backoff = min(5 * idle_loops, 30)
            print(f"No work claimed (pending={pending}); backoff {backoff}s", flush=True)
            time.sleep(backoff)


if __name__ == "__main__":
    main()
