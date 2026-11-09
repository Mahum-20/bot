with open("faithful_backtest_engine.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

new_lines = []
in_cycle_loop = False

for idx, line in enumerate(lines):
    # Find the start of the cycle loop
    if 'for reg_key, cyc in list(self.zone_cycles.items()):' in line:
        in_cycle_loop = True
        new_lines.append(line)
        continue
    
    # Inside the cycle loop, indent everything up to `metrics = self._compute_performance_metrics(trades)`
    if in_cycle_loop:
        if 'metrics = self._compute_performance_metrics(trades)' in line:
            in_cycle_loop = False
            new_lines.append(line)
        else:
            # Check if line needs extra 4 spaces
            # Lines from 363 to 482 were at 12 spaces, should be at 16 spaces
            stripped = line.lstrip()
            if not stripped:
                new_lines.append(line)
            else:
                indent = len(line) - len(stripped)
                if indent == 12:
                    new_lines.append("    " + line)
                else:
                    new_lines.append(line)
    else:
        new_lines.append(line)

with open("faithful_backtest_engine.py", "w", encoding="utf-8") as f:
    f.writelines(new_lines)

print("Successfully fixed indentation of cycle loop in faithful_backtest_engine.py")
