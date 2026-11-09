with open("htf_engine.py") as f:
    lines = f.readlines()
for i, line in enumerate(lines):
    if "lines.append" in line:
        print(f"Line {i+1}:")
        for j in range(i, min(len(lines), i+15)):
            print(f"  {lines[j].strip()}")
