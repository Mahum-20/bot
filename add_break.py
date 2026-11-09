with open("faithful_backtest_engine.py", "r", encoding="utf-8") as f:
    text = f.read()

target = '            ctx.is_executed = True\n            ctx.trade_payload = pending_order\n            self.trace_logger.log_context_completion(ctx)'
if target not in text:
    target = target.replace('\n', '\r\n')

assert target in text, "target not found"
replacement = target + ('\r\n            break' if '\r\n' in target else '\n            break')
text = text.replace(target, replacement, 1)

with open("faithful_backtest_engine.py", "w", encoding="utf-8") as f:
    f.write(text)

print("Added break statement to faithful_backtest_engine.py")
