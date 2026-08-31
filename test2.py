import sys
sys.path.append('backend')
from config import SETTINGS
print("Has OpenRouter:", SETTINGS.has_openrouter)
print("Classifier Model:", SETTINGS.classifier_model)
from control.guardrail import check_human_message
print(check_human_message("What is 5 + 5?"))
