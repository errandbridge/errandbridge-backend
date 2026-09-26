from __future__ import annotations
import requests

url = "http://localhost:8001/errands/dummy/status"
resp = requests.put(url, json={"status": "arrived_at_pickup"})
print(resp.status_code)
print(resp.json())
