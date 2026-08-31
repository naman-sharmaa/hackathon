import re

with open('backend/app.py', 'r') as f:
    content = f.read()

# Add import
if "from agents.llm_client import diagnose" not in content:
    content = content.replace("from routes import r_eval, r_report, r_session",
                              "from routes import r_eval, r_report, r_session\nfrom agents.llm_client import diagnose")

# Replace health and add diagnose
old_health = '("GET", _rx(r"/health"), lambda p, b, q: (200, {"ok": True, "service": "dealbench"})),'
new_routes = """("GET", _rx(r"/health"), lambda p, b, q: (200, {"ok": True, "service": "dealbench"})),
    ("GET", _rx(r"/api/diagnose"), lambda p, b, q: (200, diagnose(probe=q.get("probe", [""])[0].lower() == "true"))),"""

if old_health in content:
    content = content.replace(old_health, new_routes)

# Update prefixes
old_prefixes = '_API_PREFIXES = ("/session", "/eval", "/health")'
new_prefixes = '_API_PREFIXES = ("/session", "/eval", "/health", "/api")'
if old_prefixes in content:
    content = content.replace(old_prefixes, new_prefixes)

with open('backend/app.py', 'w') as f:
    f.write(content)

