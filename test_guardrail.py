import sys
sys.path.append('backend')
from config import SETTINGS
from agents.llm_client import diagnose
from control.guardrail import check_human_message

print("API Key:", SETTINGS.openrouter_api_key[:10])
print("Model:", SETTINGS.classifier_model)
valid, reason = check_human_message("how are you. I am feeling lonely")
print("Valid:", valid, "Reason:", reason)
