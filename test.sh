#!/bin/bash
# Test script for GitHub Issues Agent API endpoints

# Health check
echo "Testing health endpoint..."
curl -X GET localhost:5001/health

# Test GitHub issues endpoint with johnafariogun/go repo
echo -e "\n\nTesting issues endpoint with johnafariogun/go..."
curl -X POST localhost:5001/a2a/issues \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "message/send",
    "params": {
      "message": {
        "kind": "message",
        "role": "user",
        "parts": [
          {
            "kind": "text",
            "text": "issues for johnafariogun/go"
          }
        ]
      }
    }
  }'

# Test with specific state (closed issues)
echo -e "\n\nTesting with closed issues..."
curl -X POST localhost:5001/a2a/issues \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "2",
    "method": "message/send",
    "params": {
      "message": {
        "kind": "message",
        "role": "user",
        "parts": [
          {
            "kind": "text",
            "text": "closed issues in microsoft/vscode"
          }
        ]
      }
    }
  }'

# Test with invalid repo format (should return error)
echo -e "\n\nTesting with invalid repo format..."
curl -X POST localhost:5001/a2a/issues \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "3",
    "method": "message/send",
    "params": {
      "message": {
        "kind": "message",
        "role": "user",
        "parts": [
          {
            "kind": "text",
            "text": "show me issues invalid-repo-format"
          }
        ]
      }
    }
  }'

# For Windows PowerShell users:
echo -e "\n\nPowerShell command examples:"
echo 'Invoke-RestMethod -Uri "http://localhost:5001/a2a/issues" -Method Post -Headers @{"Content-Type"="application/json"} -Body ''{"jsonrpc":"2.0","id":"1","method":"message/send","params":{"message":{"kind":"message","role":"user","parts":[{"kind":"text","text":"issues for johnafariogun/go"}]}}}'''