import requests

login_res = requests.post("http://localhost:8000/auth/login", json={"email": "customer@test.com", "password": "password123"})
if login_res.status_code != 200:
    print("Login failed:", login_res.status_code, login_res.text)
    exit(1)
token = login_res.json()["access_token"]
print("Got token")

with open('test_local.txt', 'w') as f:
    f.write('hello world')

resp = requests.post(
    'http://localhost:8000/errands/1/attachments',
    headers={'Authorization': f'Bearer {token}'},
    files={'file': ('test_local.txt', open('test_local.txt', 'rb'))}
)
print("Upload:", resp.status_code)
if resp.status_code == 200:
    att_url = resp.json()['url']
    print(f"Downloading from {att_url}...")
    dl = requests.get(f"http://localhost:8000{att_url}?token={token}")
    print("Download:", dl.status_code)
    print("Download body:", dl.text[:100])
