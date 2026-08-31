import re

with open('frontend/index.html', 'r') as f:
    content = f.read()

# 1. Reduce setTimeout to 500ms
content = content.replace("timer = setTimeout(() => {\n            advance(session.id);\n          }, 2000);", "timer = setTimeout(() => {\n            advance(session.id);\n          }, 500);")

# 2. Fix the typing indicator so it only shows for AI turns
# Current: ${(loading || isTyping) ? html`
# Let's verify exactly what is in the file.
old_typing_cond = "${(loading || isTyping) ? html`"
new_typing_cond = "${(loading || isTyping) && session.mode[session.turn] !== 'human' ? html`"

if old_typing_cond in content:
    content = content.replace(old_typing_cond, new_typing_cond)

with open('frontend/index.html', 'w') as f:
    f.write(content)
