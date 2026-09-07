import requests

login_res = requests.post("http://localhost:8000/auth/login", json={"email": "customer@test.com", "password": "password123"})
if login_res.status_code != 200:
    print("Login failed:", login_res.status_code, login_res.text)
    exit(1)
token = login_res.json()["access_token"]

resp = requests.get(
    'http://localhost:8000/attachments',
    headers={'Authorization': f'Bearer {token}'}
)
import json
print(json.dumps(resp.json(), indent=2))
