import requests

with open('test_local.txt', 'w') as f:
    f.write('hello world')

print("Uploading...")
resp = requests.post(
    'http://localhost:8000/errands/1/attachments',
    headers={'Authorization': 'Bearer devtoken123'},
    files={'file': ('test_local.txt', open('test_local.txt', 'rb'))}
)
print("Upload status:", resp.status_code)
print("Upload body:", resp.text)

if resp.status_code == 200:
    data = resp.json()
    att_url = data['url']
    print(f"Downloading from {att_url}...")
    dl = requests.get(f"http://localhost:8000{att_url}", headers={'Authorization': 'Bearer devtoken123'})
    print("Download status:", dl.status_code)
    print("Download body:", dl.text[:100])
