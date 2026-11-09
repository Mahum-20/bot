with open("ltf_approach_engine.py", "r", encoding="utf-8") as f:
    content = f.read()

target = "    start_idx = max(0, tap_idx - 40)"
replacement = "    lookback_pre = 120 if htf_sec >= 14400 else 80\n    start_idx = max(0, tap_idx - lookback_pre)"

assert target in content, "target not found"
content = content.replace(target, replacement)

with open("ltf_approach_engine.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Updated start_idx in ltf_approach_engine.py")
