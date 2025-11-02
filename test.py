import requests
import json

payload = {
    "jsonrpc": "2.0",
    "method": "fetch_issues",
    "params": {"repo_url": "https://github.com/johnafariogun/go"},
    "id": 1
}

response = requests.post("http://localhost:8000/rpc", json=payload)
print(response.json())
