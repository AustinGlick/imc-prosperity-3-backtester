import json
from pathlib import Path

input_file = "test.log"
output_file = "visualizer.log"

out_lines = []

with open(input_file, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        if line.startswith("Sandbox logs:"):
            continue

        obj = json.loads(line)
        if "lambdaLog" in obj:
            out_lines.append(obj["lambdaLog"])

with open(output_file, "w", encoding="utf-8") as f:
    for line in out_lines:
        f.write(line)
        f.write("\n")

print(f"Wrote {output_file}")