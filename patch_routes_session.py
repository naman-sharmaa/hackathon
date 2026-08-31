import re

with open('backend/routes/report.py', 'r') as f:
    pass # just to check, not needed.

with open('backend/routes/session.py', 'r') as f:
    content = f.read()

old_post_message = """    human_message = body.get("message")
    produced = []

    result = session.advance_turn(human_message=human_message)"""

new_post_message = """    human_message = body.get("message")
    
    if human_message:
        from control.guardrail import check_human_message
        is_valid, reason = check_human_message(human_message)
        if not is_valid:
            return 400, {"error": reason}

    produced = []

    result = session.advance_turn(human_message=human_message)"""

if old_post_message in content:
    content = content.replace(old_post_message, new_post_message)
else:
    print("Could not find the exact string.")

with open('backend/routes/session.py', 'w') as f:
    f.write(content)

