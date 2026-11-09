import json
from ltf_approach_engine import is_htf_box_active, is_qualifying_htf_zone
from htf_engine import HTFEngine

c_4h = json.load(open('data/btcusdt_4h_1y_oct2025_oct2026.json'))
c_5m = json.load(open('data/btcusdt_5m_1y_oct2025_oct2026.json'))
boxes = HTFEngine(lookback_bars=len(c_4h), show_tjl_boxes=True, tjl_extend=True).run(c_4h)['boxes']

c_time = c_5m[1500]['time']
print(f"c_time: {c_time}")
active = []
for b in boxes:
    is_qual = is_qualifying_htf_zone(b)
    is_act = is_htf_box_active(b, c_time)
    if is_act:
        active.append(b)
    print(f"box {b.get('text')} left={b.get('left')} right={b.get('right')} is_qual={is_qual} is_act={is_act} mit={b.get('is_mitigated')}")
print(f"Total active boxes at {c_time}: {len(active)}")
