import sys
import time

sys.path.append('/app')

from orchestration.continuous_processor import (  # pylint: disable=wrong-import-position
    WorkQueue,
    process_wire_detection,
    ENABLE_WIRE_DETECTION,
    WIRE_DETECTION_BATCH_SIZE,
)


def run_batches(max_iterations: int) -> int:
    processed = 0
    idle_loops = 0

    for iteration in range(1, max_iterations + 1):
        counts = WorkQueue.get_counts()
        pending = counts.get("wire_detection_pending", 0) or 0
        print(f"Iteration {iteration}: pending={pending}", flush=True)

        if pending == 0:
            print("No pending articles remain for wire detection.", flush=True)
            break

        batch = max(1, min(pending, WIRE_DETECTION_BATCH_SIZE))
        if process_wire_detection(batch):
            processed += batch
            idle_loops = 0
            print(f"Processed up to {batch} article(s); total processed ≈ {processed}", flush=True)
            time.sleep(1)
        else:
            idle_loops += 1
            backoff = min(5 * idle_loops, 30)
            print(f"No work claimed; backoff {backoff}s", flush=True)
            time.sleep(backoff)

    return processed


def main() -> None:
    if not ENABLE_WIRE_DETECTION:
        print("Wire detection is disabled via environment flag; aborting.", flush=True)
        return

    total_processed = run_batches(max_iterations=50)
    print(f"Completed limited run; attempted ≈ {total_processed} article(s).", flush=True)


if __name__ == "__main__":
    main()
