import json
from ltf_approach_engine import compute_ltf_approach_structure
from htf_engine import HTFEngine

c_4h = json.load(open('data/btcusdt_4h_1y_oct2025_oct2026.json'))
c_5m = json.load(open('data/btcusdt_5m_1y_oct2025_oct2026.json'))
boxes = HTFEngine(lookback_bars=len(c_4h), show_tjl_boxes=True, tjl_extend=True).run(c_4h)['boxes']

res = compute_ltf_approach_structure(c_5m[1643]['time'], c_5m, boxes, 14400, c_4h)
tap_info = res.get("tap_info")
print("tap_info at 1643 with current code:", tap_info is not None)
