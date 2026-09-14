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
print("workflow frontend checks simplified")
