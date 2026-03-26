import json

input_file = "test.log"
output_file = "visualizer.log"

out_lines = []

with open(input_file, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()

        # Skip empty lines
        if not line:
            continue

        # Skip non-JSON lines
        if not line.startswith("{"):
            continue

        try:
            obj = json.loads(line)
        except:
            continue

        if "lambdaLog" in obj:
            out_lines.append(obj["lambdaLog"])

with open(output_file, "w", encoding="utf-8") as f:
    for line in out_lines:
        f.write(line + "\n")

print("Done → visualizer.log ready")