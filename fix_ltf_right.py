with open('ltf_approach_engine.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

count = 0
new_lines = []
for line in lines:
    if 'b_right = b.get("right") or b.get("end_time") or 9999999999' in line:
        indent = line[:line.find('b_right')]
        new_lines.append(f'{indent}b_right = b.get("mitigated_time") if (b.get("is_mitigated") or b.get("is_broken")) else 9999999999\n')
        count += 1
    else:
        new_lines.append(line)

with open('ltf_approach_engine.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print(f"Replaced {count} occurrences in ltf_approach_engine.py")
