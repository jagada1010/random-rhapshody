
import os
import sys
import time
import signal
import subprocess
from pathlib import Path
from datetime import datetime

# Project configuration
PROJECT_DIR = Path(r"E:\To Learn\Pet-Project-Latest\random-rhapshody")
PYTHON_EXE = r"C:\Program Files\Python310\python.exe"
MAIN_SCRIPT = PROJECT_DIR / "main.py"

LOG_DIR = PROJECT_DIR / "logs"
LOG_FILE = LOG_DIR / "service.log"

INTERVAL_SECONDS = 600  # 10 minutes

stop_event = False


def handle_stop(signum, frame):
    global stop_event
    stop_event = True


signal.signal(signal.SIGTERM, handle_stop)
signal.signal(signal.SIGINT, handle_stop)


def log(message, log_handle):
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    log_handle.write(f"[{timestamp}] {message}\n")
    log_handle.flush()


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    if not MAIN_SCRIPT.exists():
        raise FileNotFoundError(f"Cannot find: {MAIN_SCRIPT}")

    if not Path(PYTHON_EXE).exists():
        raise FileNotFoundError(f"Cannot find Python: {PYTHON_EXE}")

    with LOG_FILE.open("a", encoding="utf-8", buffering=1) as log_handle:
        log("BookMyShow monitor service started.", log_handle)

        while not stop_event:
            log("Starting monitor execution.", log_handle)

            process = subprocess.Popen(
                [PYTHON_EXE, "-u", str(MAIN_SCRIPT)],
                cwd=str(PROJECT_DIR),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
            )

            while process.poll() is None and not stop_event:
                time.sleep(1)

            if process.poll() is None:
                log("Stop requested. Terminating monitor execution.", log_handle)
                process.terminate()

                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    log("Monitor did not stop; forcing termination.", log_handle)
                    process.kill()
                    process.wait()

            exit_code = process.poll()
            log(f"Monitor execution ended. Exit code: {exit_code}", log_handle)

            if stop_event:
                break

            log("Next execution in 10 minutes.", log_handle)

            for _ in range(INTERVAL_SECONDS):
                if stop_event:
                    break
                time.sleep(1)

        log("BookMyShow monitor service stopped.", log_handle)


if __name__ == "__main__":
    main()
