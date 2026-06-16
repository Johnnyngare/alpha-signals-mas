import schedule
import time
import subprocess
import sys
from datetime import datetime, timezone


def run_pipeline_job(mode_flag: str = "") -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n[Scheduler] Triggering pipeline at {timestamp}")

    cmd = [sys.executable, "run.py", "--auto"]
    if mode_flag:
        cmd.append(mode_flag)

    try:
        result = subprocess.run(cmd, capture_output=False, timeout=300)
        if result.returncode == 0:
            print(f"[Scheduler] Pipeline completed successfully.")
        else:
            print(f"[Scheduler] Pipeline exited with code {result.returncode}.")
    except subprocess.TimeoutExpired:
        print("[Scheduler] Pipeline timed out after 300 seconds.")
    except Exception as e:
        print(f"[Scheduler] Unexpected error: {e}")


def main() -> None:
    print("[Scheduler] Alpha Signals MAS — Scheduler starting.")
    print("[Scheduler] Schedule: Value Sheet at 08:00, 12:00, 16:00, 20:00 UTC")
    print("[Scheduler] Schedule: Arb Digest at 17:30, 19:30, 21:30 UTC")

    schedule.every().day.at("08:00").do(run_pipeline_job)
    schedule.every().day.at("12:00").do(run_pipeline_job)
    schedule.every().day.at("16:00").do(run_pipeline_job)
    schedule.every().day.at("20:00").do(run_pipeline_job)

    schedule.every().day.at("17:30").do(run_pipeline_job, mode_flag="--arb")
    schedule.every().day.at("19:30").do(run_pipeline_job, mode_flag="--arb")
    schedule.every().day.at("21:30").do(run_pipeline_job, mode_flag="--arb")

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()