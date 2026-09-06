"""
Fast concurrent translation script for all categories and event types from events.json
into all 9 supported Indian languages, saving directly into translations.json.
"""
import asyncio
import json
import os
import sys
import httpx

LANGS = ["hi", "mr", "gu", "te", "kn", "ml", "bn", "pa", "or"]

async def translate_single(client, text, lang, sem):
    async with sem:
        for client_type in ("gtx", "dict-chrome-ex", "it", "at"):
            try:
                resp = await client.get(
                    "https://translate.googleapis.com/translate_a/single",
                    params={
                        "client": client_type,
                        "sl": "en",
                        "tl": lang,
                        "dt": "t",
                        "q": text,
                    },
                    timeout=6.0
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data and isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
                        txt = "".join(part[0] for part in data[0] if part and part[0])
                        if txt:
                            return text, lang, txt
            except Exception:
                continue
    return text, lang, text

async def main():
    with open("events.json", "r", encoding="utf-8") as f:
        events_data = json.load(f)

    # Collect all categories and event types
    items_to_translate = list(events_data.keys())
    for ev_list in events_data.values():
        for ev in ev_list:
            if ev not in items_to_translate:
                items_to_translate.append(ev)

    if "Tree Plantation" not in items_to_translate:
        items_to_translate.append("Tree Plantation")

    print(f"Total items to translate: {len(items_to_translate)}")

    # Load existing translations to skip already translated ones
    with open("translations.json", "r", encoding="utf-8") as f:
        existing = json.load(f)

    tasks = []
    sem = asyncio.Semaphore(15)  # 15 concurrent requests
    limits = httpx.Limits(max_connections=30, max_keepalive_connections=15)

    async with httpx.AsyncClient(limits=limits, timeout=10.0) as client:
        for item in items_to_translate:
            clean = item.strip()
            if not clean:
                continue
            for lang in LANGS:
                if clean in existing and lang in existing[clean] and existing[clean][lang] != clean:
                    continue  # Already translated
                tasks.append(translate_single(client, clean, lang, sem))

        print(f"Tasks to execute: {len(tasks)}")
        results = await asyncio.gather(*tasks)

    # Merge results
    for text, lang, trans in results:
        if text not in existing:
            existing[text] = {}
        existing[text][lang] = trans

    with open("translations.json", "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    print(f"Successfully updated translations.json! Total keys: {len(existing)}")

if __name__ == "__main__":
    asyncio.run(main())
