import requests

# Put your gsk_ key here to test it
API_KEY = "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"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

payload = {
    "model": "llama-3.1-8b-instant",
    "messages": [{"role": "user", "content": "Say hello!"}]
}

print("Testing key...")
response = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
print(f"Status Code: {response.status_code}")
print(f"Response: {response.text}")