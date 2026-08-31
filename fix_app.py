with open('backend/app.py', 'r') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if line.startswith('from agents.llm_client import diagnose'):
        continue
    new_lines.append(line)

# Insert after __future__
for i, line in enumerate(new_lines):
    if line.startswith('from __future__ import annotations'):
        new_lines.insert(i + 1, 'from agents.llm_client import diagnose\n')
        break

with open('backend/app.py', 'w') as f:
    f.writelines(new_lines)
