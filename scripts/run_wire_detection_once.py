import sys
import time

sys.path.append('/app')

from orchestration.continuous_processor import (  # pylint: disable=wrong-import-position
    WorkQueue,
    process_wire_detection,
    ENABLE_WIRE_DETECTION,
    WIRE_DETECTION_BATCH_SIZE,
)


def print_counts(header: str) -> int:
    counts = WorkQueue.get_counts()
    pending = counts.get("wire_detection_pending", 0) or 0
    print(f"{header}: pending={pending}", flush=True)
    return pending


def main() -> None:
    if not ENABLE_WIRE_DETECTION:
        print("Wire detection disabled; aborting.", flush=True)
        return

    print("Running single MediaCloud detection batch...", flush=True)
    before = print_counts("Before")
    batch = max(1, min(before, WIRE_DETECTION_BATCH_SIZE))
    if before == 0:
        print("Nothing to process.", flush=True)
        return

    processed = process_wire_detection(batch)
    time.sleep(1)
    after = print_counts("After")

    print(f"Requested batch size: {batch}", flush=True)
    print(f"Processing call returned: {processed}", flush=True)
    print(f"Pending delta: {before - after}", flush=True)


if __name__ == "__main__":
    main()
