"""
SahyogSutra Translation & Performance Benchmark.
Measures latency, memory, concurrency, and cache performance across languages.
"""

import asyncio
import os
import sys
import time

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.translation_service import (
    translate_single,
    translate_event_data,
    translate_events_batch,
    get_cached_event_field,
    close_translation_client,
    TRANSLATION_WORKERS,
    _sem
)


def get_process_memory():
    """Reads VmRSS and VmHWM from /proc/self/status on Linux."""
    try:
        with open("/proc/self/status", "r") as f:
            lines = f.readlines()
        res = {}
        for line in lines:
            if line.startswith("VmRSS:"):
                res["VmRSS"] = line.split()[1] + " kB"
            elif line.startswith("VmHWM:"):
                res["VmHWM"] = line.split()[1] + " kB"
            elif line.startswith("Threads:"):
                res["Threads"] = line.split()[1]
        return res
    except Exception:
        return {"VmRSS": "N/A", "VmHWM": "N/A", "Threads": "N/A"}


async def benchmark_single_event():
    print("\n" + "=" * 60)
    print("1. SINGLE EVENT TRANSLATION BENCHMARK (CONCURRENT FIELDS)")
    print("=" * 60)

    sample_event = {
        "eventid": 101,
        "eventname": "Clean Earth Community Drive",
        "description": "Join volunteers to clean and rejuvenate the urban river banks.",
        "location": "Riverfront Promenade, Jaipur",
        "category": "Environment",
        "username": "green_warrior",
        "email": "volunteer@example.com",
        "eventstartdate": "2026-10-20",
        "eventenddate": "2026-10-21",
        "likes": 42
    }

    # English (should be instantaneous)
    t0 = time.time()
    en_res = await translate_event_data(sample_event, "en")
    t_en = (time.time() - t0) * 1000
    print(f"[*] English (en):          {t_en:6.2f} ms | name='{en_res['eventname']}'")

    # Hindi (first load - uncached, concurrent fields)
    t0 = time.time()
    hi_res = await translate_event_data(sample_event, "hi")
    t_hi_uncached = (time.time() - t0) * 1000
    print(f"[*] Hindi (hi) [Uncached]: {t_hi_uncached:6.2f} ms | name='{hi_res['eventname']}' | cat='{hi_res['category']}'")

    # Hindi (second load - cached LRU+TTL)
    t0 = time.time()
    hi_res_cached = await translate_event_data(sample_event, "hi")
    t_hi_cached = (time.time() - t0) * 1000
    print(f"[*] Hindi (hi) [Cached]:   {t_hi_cached:6.2f} ms | name='{hi_res_cached['eventname']}'")

    # Marathi (mr)
    t0 = time.time()
    mr_res = await translate_event_data(sample_event, "mr")
    t_mr = (time.time() - t0) * 1000
    print(f"[*] Marathi (mr):          {t_mr:6.2f} ms | name='{mr_res['eventname']}'")

    # Gujarati (gu)
    t0 = time.time()
    gu_res = await translate_event_data(sample_event, "gu")
    t_gu = (time.time() - t0) * 1000
    print(f"[*] Gujarati (gu):         {t_gu:6.2f} ms | name='{gu_res['eventname']}'")


async def benchmark_multiple_events():
    print("\n" + "=" * 60)
    print("2. MULTIPLE EVENTS BENCHMARK (BOUNDED GLOBAL CONCURRENCY)")
    print(f"   Configured Concurrency Semaphore: {TRANSLATION_WORKERS} workers")
    print("=" * 60)

    base_events = [
        {
            "eventid": i,
            "eventname": f"Community Tree Plantation Project #{i}",
            "description": f"Planting native saplings in urban sector #{i % 10} to increase tree cover.",
            "location": f"Sector #{i % 10} Public Park, Zone {i % 5}",
            "category": "Afforestation",
            "username": f"user_{i}",
            "likes": i * 3
        }
        for i in range(1, 51)
    ]

    for count in [1, 5, 20, 50]:
        subset = base_events[:count]
        t0 = time.time()
        results = await translate_events_batch(subset, "hi")
        elapsed = (time.time() - t0) * 1000
        per_event = elapsed / count
        mem = get_process_memory()
        print(f"[*] {count:2d} events ({count * 4:3d} fields): {elapsed:7.2f} ms total ({per_event:6.2f} ms/event) | RAM RSS: {mem.get('VmRSS')} | Threads: {mem.get('Threads')}")


async def benchmark_http_routes():
    print("\n" + "=" * 60)
    print("3. HTTP ROUTES LATENCY BENCHMARK (FastAPI /show_campaigns & /event)")
    print("=" * 60)

    from starlette.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        # Route 1: /show_campaigns in English
        client.post("/setlanguage/en")
        t0 = time.time()
        r_en = client.get("/show_campaigns")
        t_en = (time.time() - t0) * 1000
        print(f"[*] GET /show_campaigns [English]:       {t_en:6.2f} ms (status: {r_en.status_code})")

        # Route 2: /show_campaigns in Hindi (first request)
        client.post("/setlanguage/hi")
        t0 = time.time()
        r_hi_1 = client.get("/show_campaigns")
        t_hi_1 = (time.time() - t0) * 1000
        print(f"[*] GET /show_campaigns [Hindi - 1st]:   {t_hi_1:6.2f} ms (status: {r_hi_1.status_code})")

        # Route 3: /show_campaigns in Hindi (cached request)
        t0 = time.time()
        r_hi_2 = client.get("/show_campaigns")
        t_hi_2 = (time.time() - t0) * 1000
        print(f"[*] GET /show_campaigns [Hindi - Cached]:{t_hi_2:6.2f} ms (status: {r_hi_2.status_code})")

        # Route 4: /show_campaigns in Marathi
        client.post("/setlanguage/mr")
        t0 = time.time()
        r_mr = client.get("/show_campaigns")
        t_mr = (time.time() - t0) * 1000
        print(f"[*] GET /show_campaigns [Marathi]:       {t_mr:6.2f} ms (status: {r_mr.status_code})")

    mem = get_process_memory()
    print("\n" + "=" * 60)
    print(f"FINAL BENCHMARK RESOURCE FOOTPRINT: VmRSS={mem.get('VmRSS')}, VmHWM={mem.get('VmHWM')}, Threads={mem.get('Threads')}")
    print("=" * 60)


async def main():
    try:
        await benchmark_single_event()
        await benchmark_multiple_events()
        await benchmark_http_routes()
    finally:
        await close_translation_client()


if __name__ == "__main__":
    asyncio.run(main())
