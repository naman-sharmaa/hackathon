import sys
sys.path.append('backend')
from config import SETTINGS
from agents.llm_client import diagnose

print("Settings Has OpenRouter:", SETTINGS.has_openrouter)
print("Config API Key:", SETTINGS.openrouter_api_key[:10] if SETTINGS.openrouter_api_key else None)
print(diagnose(probe=False))
