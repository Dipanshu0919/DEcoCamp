"""
SahyogSutra Translation Service.
Provides asynchronous, bounded-concurrency text translation using googletrans.
Avoids thread-per-field overhead and maintains bounded in-memory translation caches.
"""

import asyncio
from collections import OrderedDict
import json
import logging
import os
import threading
import time
from typing import Dict, Any, List, Optional
import httpx

logger = logging.getLogger(__name__)

# Configurable bounded concurrency (default 3 workers)
TRANSLATION_WORKERS = int(os.environ.get("TRANSLATION_WORKERS", "3"))
_sem = asyncio.Semaphore(TRANSLATION_WORKERS)

# Bounded in-memory translation storage (static UI strings)
_MAX_TRANSLATION_ENTRIES = 1000
_all_translations: Dict[str, Dict[str, str]] = {}
_ui_language_dicts: Dict[str, Dict[str, str]] = {}
_translations_dirty = False
_translations_lock = threading.Lock()

# Bounded LRU + TTL cache for dynamic content (event details, descriptions)
_MAX_EVENT_CACHE = 500
_EVENT_CACHE_TTL = 3600  # 1 hour
_event_cache: OrderedDict = OrderedDict()
_event_cache_lock = threading.Lock()

# User-facing fields to translate for events
DISPLAY_FIELDS = ("eventname", "description", "location", "category")

_http_client: Optional[httpx.AsyncClient] = None
_client_lock = asyncio.Lock()


def _rebuild_ui_language_dicts():
    """Builds fast per-language lookup dictionaries from _all_translations for instant page rendering."""
    global _ui_language_dicts
    new_dicts: Dict[str, Dict[str, str]] = {}
    with _translations_lock:
        for source_text, lang_map in _all_translations.items():
            if not isinstance(lang_map, dict):
                continue
            for lang, trans_text in lang_map.items():
                if lang not in new_dicts:
                    new_dicts[lang] = {}
                new_dicts[lang][source_text] = trans_text
    _ui_language_dicts = new_dicts


def get_ui_translation_dict(lang: str) -> Dict[str, str]:
    """
    Returns the precomputed in-memory page-level translation dictionary for the requested language.
    For 'en', returns an empty dict (handled as zero-overhead identity).
    For other languages, returns the source_text -> translated_text dictionary in O(1) time.
    """
    if not lang or lang == "en":
        return {}
    return _ui_language_dicts.get(lang, {})


def get_cached_event_field(text: str, lang: str) -> Optional[str]:
    """Retrieves cached translation from bounded LRU cache if not expired."""
    if not lang or lang == "en":
        return text
    key = f"{lang}:{text.strip()}"
    with _event_cache_lock:
        if key in _event_cache:
            val, exp = _event_cache[key]
            if time.time() < exp:
                _event_cache.move_to_end(key)
                return val
            else:
                del _event_cache[key]
    return None


def store_cached_event_field(text: str, lang: str, translated: str):
    """Stores translated text in bounded LRU cache with TTL."""
    key = f"{lang}:{text.strip()}"
    with _event_cache_lock:
        if len(_event_cache) >= _MAX_EVENT_CACHE:
            _event_cache.popitem(last=False)  # Evict oldest entry
        _event_cache[key] = (translated, time.time() + _EVENT_CACHE_TTL)


async def get_translation_client() -> httpx.AsyncClient:
    """Returns a shared, pooled AsyncClient with strict 2.5s timeout to prevent hanging."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        async with _client_lock:
            if _http_client is None or _http_client.is_closed:
                _http_client = httpx.AsyncClient(
                    timeout=2.5,
                    limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                    }
                )
    return _http_client


async def close_translation_client():
    """Closes the shared translation HTTP client gracefully on shutdown."""
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


def load_translations(filepath: str = "translations.json"):
    """Loads pre-translated strings into bounded memory on startup."""
    global _all_translations
    if not os.path.exists(filepath):
        return
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            with _translations_lock:
                # Keep up to _MAX_TRANSLATION_ENTRIES to prevent unbounded growth
                if len(data) > _MAX_TRANSLATION_ENTRIES:
                    _all_translations = dict(list(data.items())[-_MAX_TRANSLATION_ENTRIES:])
                else:
                    _all_translations = data
        _rebuild_ui_language_dicts()
        logger.info("Loaded %d translation entries across %d language maps.", len(_all_translations), len(_ui_language_dicts))
    except Exception as e:
        logger.error("Error loading translations: %s", e)


def save_translations_if_dirty(filepath: str = "translations.json"):
    """Saves updated translations to disk only if modified."""
    global _translations_dirty
    if not _translations_dirty:
        return
    with _translations_lock:
        if not _translations_dirty:
            return
        try:
            tmp = filepath + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(_all_translations, f, indent=2, ensure_ascii=False)
            os.replace(tmp, filepath)
            _translations_dirty = False
        except Exception as e:
            logger.error("Failed saving translations to disk: %s", e)


def get_cached_translation(text: str, lang: str) -> Optional[str]:
    """Retrieves cached translation if available."""
    if not lang or lang == "en":
        return text
    clean_text = " ".join(text.replace("\n", " ").split())
    with _translations_lock:
        entry = _all_translations.get(clean_text)
        if entry and lang in entry:
            return entry[lang]
    return None


def store_cached_translation(text: str, lang: str, translated: str):
    """Stores translation in bounded cache and marks dirty."""
    global _translations_dirty
    clean_text = " ".join(text.replace("\n", " ").split())
    with _translations_lock:
        if len(_all_translations) >= _MAX_TRANSLATION_ENTRIES:
            # Evict oldest entry
            oldest_key = next(iter(_all_translations))
            del _all_translations[oldest_key]

        entry = _all_translations.setdefault(clean_text, {})
        entry[lang] = translated
        _translations_dirty = True

        if lang not in _ui_language_dicts:
            _ui_language_dicts[lang] = {}
        _ui_language_dicts[lang][clean_text] = translated


async def translate_single(text: str, lang: str) -> str:
    """Translates a single string asynchronously with client rotation and caching."""
    if not text or not text.strip() or not lang or lang == "en":
        return text

    # Skip pure numbers, dates, punctuation (e.g. '2026-09-10 08:00', '12345')
    if not any(c.isalpha() for c in text):
        return text

    clean_text = " ".join(text.replace("\n", " ").split())
    cached = get_cached_translation(clean_text, lang) or get_cached_event_field(clean_text, lang)
    if cached:
        return cached

    # 1. Primary: Try pooled lightweight HTTP request with rotated Google Translate clients
    try:
        client = await get_translation_client()
        async with _sem:
            # Re-check cache under semaphore
            cached = get_cached_translation(clean_text, lang) or get_cached_event_field(clean_text, lang)
            if cached:
                return cached

            for client_type in ("dict-chrome-ex", "it", "at", "gtx"):
                try:
                    resp = await client.get(
                        "https://translate.googleapis.com/translate_a/single",
                        params={
                            "client": client_type,
                            "sl": "auto",
                            "tl": lang,
                            "dt": "t",
                            "q": clean_text,
                        },
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        if data and isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
                            result_text = "".join(part[0] for part in data[0] if part and part[0])
                            if result_text:
                                store_cached_translation(clean_text, lang, result_text)
                                store_cached_event_field(clean_text, lang, result_text)
                                return result_text
                except Exception as ex:
                    logger.debug("Client '%s' translation error: %s", client_type, ex)
                    continue
    except Exception as e:
        logger.debug("Pooled translation failed for '%s': %s", clean_text[:30], e)

    # 2. Secondary fallback: googletrans.Translator
    try:
        from googletrans import Translator
        async with _sem:
            async with Translator() as t:
                res = await t.translate(clean_text, dest=lang)
                if res and res.text:
                    store_cached_translation(clean_text, lang, res.text)
                    store_cached_event_field(clean_text, lang, res.text)
                    return res.text
    except Exception as e:
        logger.debug("googletrans fallback failed for '%s': %s", clean_text[:30], e)

    return text


async def translate_event_data(event_dict: Dict[str, Any], lang: str) -> Dict[str, Any]:
    """
    Translates user-facing display fields of an event dictionary concurrently.
    Non-display fields (eventid, email, username, dates/times, likes) are untouched.
    Concurrently executes translatable fields: max(T1, T2, T3, T4).
    """
    if not lang or lang == "en" or not event_dict:
        return dict(event_dict)

    translated = dict(event_dict)
    translatable_keys = [k for k in DISPLAY_FIELDS if k in event_dict and event_dict[k]]

    tasks = [translate_single(str(event_dict[k]), lang) for k in translatable_keys]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for k, res in zip(translatable_keys, results):
        if not isinstance(res, Exception) and res:
            translated[k] = res

    return translated


async def translate_events_batch(events: List[Dict[str, Any]], lang: str) -> List[Dict[str, Any]]:
    """
    Translates a list of event dictionaries concurrently using bounded concurrency.
    All fields flow through the shared bounded semaphore to prevent API burst limits.
    """
    if not lang or lang == "en" or not events:
        return [dict(e) for e in events]

    tasks = [translate_event_data(e, lang) for e in events]
    return await asyncio.gather(*tasks)


async def translate_dict_fields(data: Dict[str, Any], lang: str) -> Dict[str, str]:
    """
    Translates dictionary values concurrently using asyncio.gather.
    Replaces raw per-field thread spawning.
    """
    if not lang or lang == "en":
        return {k: str(v) for k, v in data.items()}

    keys = list(data.keys())
    tasks = [translate_single(str(data[k]), lang) for k in keys]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    output = {}
    for k, res in zip(keys, results):
        if isinstance(res, Exception):
            output[k] = str(data[k])
        else:
            output[k] = res
    return output


def sync_translate_text(text: str, lang: str = "en") -> str:
    """
    Synchronous lookup for Jinja template filter.
    Returns cached translation instantly (0ms), or original source text fallback.
    Guarantees zero blocking and zero event loop congestion.
    """
    if not text or not lang or lang == "en":
        return text
    clean_text = " ".join(text.replace("\n", " ").split())
    cached = get_cached_translation(clean_text, lang) or get_cached_event_field(clean_text, lang)
    if cached:
        return cached
    return text

