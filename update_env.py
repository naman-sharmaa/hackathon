with open('backend/.env', 'r') as f:
    content = f.read()

content = content.replace("BUYER_MODEL=meta-llama/llama-3.1-8b-instruct:free", "BUYER_MODEL=poolside/laguna-s-2.1:free")
content = content.replace("SELLER_MODEL=meta-llama/llama-3.1-8b-instruct:free", "SELLER_MODEL=nvidia/nemotron-3.5-lightning:free")
content = content.replace("CLASSIFIER_MODEL=meta-llama/llama-3.1-8b-instruct:free", "CLASSIFIER_MODEL=google/gemma-4-31b-it:free")

with open('backend/.env', 'w') as f:
    f.write(content)
