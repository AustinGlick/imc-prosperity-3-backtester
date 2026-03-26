import json
import re
from pathlib import Path

input_file = Path("test.log")
output_file = Path("visualizer.log")

text = input_file.read_text(encoding="utf-8")

# Find every lambdaLog string, even across multiline JSON blocks.
pattern = re.compile(r'"lambdaLog"\s*:\s*"((?:\\.|[^"\\])*)"', re.DOTALL)

out_lines = []
for match in pattern.finditer(text):
    escaped = match.group(1)
    # Unescape the JSON string content
    raw = json.loads(f'"{escaped}"')
    out_lines.append(raw)

output_file.write_text("\n".join(out_lines), encoding="utf-8")
print(f"Wrote {output_file} with {len(out_lines)} entries")