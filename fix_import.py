with open("faithful_backtest_engine.py", "r", encoding="utf-8") as f:
    text = f.read()

target = "from ltf_approach_engine import (\n    clean_box_name,\n    compute_ltf_approach_structure,\n    compute_15m_atr\n)"
if target not in text:
    target = target.replace("\n", "\r\n")

assert target in text, "target not found"
replacement = target.replace("compute_15m_atr", "compute_15m_atr,\n    is_valid_tap_approach" if "\n" in target and "\r\n" not in target else "compute_15m_atr,\r\n    is_valid_tap_approach")

text = text.replace(target, replacement, 1)

with open("faithful_backtest_engine.py", "w", encoding="utf-8") as f:
    f.write(text)

print("Imported is_valid_tap_approach in faithful_backtest_engine.py")
