"""
SahyogSutra Diagnostic Memory & Thread Checker.
Simulates real workloads and measures process RSS, high-water mark,
active threads, and connection pool state.
"""

import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def get_proc_status():
    status = {"VmRSS": "0 kB", "VmHWM": "0 kB", "Threads": 1}
    try:
        with open("/proc/self/status", "r") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = parts[1].strip()
                    if key in ("VmRSS", "VmHWM", "Threads"):
                        status[key] = val
    except Exception as e:
        status["error"] = str(e)
    return status

def report(stage: str):
    stat = get_proc_status()
    threads = threading.enumerate()
    thread_names = [t.name for t in threads]
    print(f"\n[{stage}]")
    print(f"  VmRSS:        {stat.get('VmRSS')}")
    print(f"  VmHWM (Peak): {stat.get('VmHWM')}")
    print(f"  OS Threads:   {stat.get('Threads')}")
    print(f"  Py Threads:   {len(threads)} ({', '.join(thread_names)})")

async def run_memory_benchmark():
    report("1. Initial Python Base")

    # Measure import
    from app.main import app, lifespan
    report("2. After importing app")

    # Start lifespan (simulates production startup)
    async with lifespan(app):
        report("3. Idle RSS after Application Startup")

        from starlette.testclient import TestClient
        with TestClient(app) as client:
            # 1. Home page
            client.get("/?preview=true")
            report("4. After GET / (Home Page)")

            # 2. Campaigns
            client.get("/show_campaigns")
            report("5. After GET /show_campaigns")

            # 3. Leaderboard
            client.get("/api/leaderboard")
            report("6. After GET /api/leaderboard")

            # 4. View event & chat
            client.get("/event/70")
            client.get("/group-chat/from-event/70")
            report("7. After GET /event/70 and /group-chat/from-event/70")

            # 5. Repeated requests loop (50 requests across endpoints)
            for i in range(50):
                client.get("/api/leaderboard")
                client.get("/show_campaigns")
            report("8. After 50 Repeated Requests (Cache & Pool Stability Check)")

    report("9. After Lifespan Shutdown")

if __name__ == "__main__":
    asyncio.run(run_memory_benchmark())
