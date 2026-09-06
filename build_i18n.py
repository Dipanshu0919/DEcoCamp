"""
Build script: Generate static/i18n/<lang>.js bundles from translations.json.
Run: venv/bin/python build_i18n.py
"""
import json, re, os

ROOT = "/home/dipanshu/Desktop/SahyogSutra"
TRANS_FILE = f"{ROOT}/translations.json"
OUT_DIR = f"{ROOT}/static/i18n"
SUPPORTED_LANGS = ["hi", "mr", "gu", "te", "kn", "ml", "bn", "pa", "or"]

os.makedirs(OUT_DIR, exist_ok=True)

with open(TRANS_FILE, encoding="utf-8") as f:
    translations = json.load(f)

def make_key(source):
    s = source.strip()
    s = re.sub(r"[.!?…]+$", "", s)
    s = s.lower()
    s = s.replace("&", "and")
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = s.strip("_")
    if len(s) > 60:
        s = s[:60].rsplit("_", 1)[0]
    return s or "key"

key_map = {}
used_keys = {}

for source in sorted(translations.keys()):
    base = make_key(source)
    key = base
    n = 2
    while key in used_keys and used_keys[key] != source:
        key = f"{base}_{n}"
        n += 1
    key_map[source] = key
    used_keys[key] = source

reverse_map = {v: k for k, v in key_map.items()}
with open(f"{OUT_DIR}/_key_map.json", "w", encoding="utf-8") as f:
    json.dump({"key_to_source": reverse_map, "source_to_key": key_map}, f, indent=2, ensure_ascii=False)

def js_esc(s):
    if not isinstance(s, str):
        s = str(s)
    s = s.replace("\\", "\\\\")
    s = s.replace('"', '\\"')
    s = s.replace("\n", "\\n")
    s = s.replace("\r", "")
    s = s.replace("\t", "\\t")
    s = s.replace("</", "<\\/")
    return s

def write_bundle(lang, data):
    path = f"{OUT_DIR}/{lang}.js"
    entries = []
    for key in sorted(data.keys()):
        val = data[key]
        entries.append(f'  "{js_esc(key)}": "{js_esc(val)}"')
    
    body = ",\n".join(entries)
    content = (
        f"/* SahyogSutra i18n bundle — {lang} */\n"
        f"window.SS_I18N = (function () {{\n"
        f"  var d = {{\n"
        f"{body}\n"
        f"  }};\n"
        f"  return {{\n"
        f"    get: function (k) {{ return d[k] || null; }},\n"
        f"    data: d\n"
        f"  }};\n"
        f"}}());\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    size = os.path.getsize(path)
    print(f"  {lang}.js — {len(data)} keys — {size} bytes")

# en.js
en_data = {key_map[src]: src for src in translations}
write_bundle("en", en_data)

# Other languages
for lang in SUPPORTED_LANGS:
    lang_data = {}
    for source, lang_map in translations.items():
        key = key_map[source]
        lang_data[key] = lang_map.get(lang, source)
    write_bundle(lang, lang_data)

print(f"\nGenerated all bundles in {OUT_DIR}/")
