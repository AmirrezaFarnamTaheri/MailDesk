from pathlib import Path

root = Path(__file__).resolve().parents[2]

for name in ("ci.yml", "build-windows.yml"):
    path = root / ".github" / "workflows" / name
    text = path.read_text(encoding="utf-8")
    text = text.replace("          node --check mailmerge_app/static/safety.js\n", "")
    text = text.replace("          node --check mailmerge_app/static/safety.js\r\n", "")
    if "safety.js" in text:
        raise RuntimeError(f"obsolete safety.js workflow reference remains in {name}")
    path.write_text(text, encoding="utf-8")

# Regex replacement strings in these transforms contain source-code escapes.
# Preserve replacement text verbatim instead of letting re.sub reinterpret it.
for name in ("backend.py", "frontend.py"):
    path = root / ".github" / "product-simplification" / name
    text = path.read_text(encoding="utf-8")
    old = "output, count = re.subn(pattern, replacement, text, count=1, flags=flags)"
    new = "output, count = re.subn(pattern, lambda _match: replacement, text, count=1, flags=flags)"
    if old not in text:
        raise RuntimeError(f"literal replacement patch target missing in {name}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")

print("workflow and transform plumbing simplified")
