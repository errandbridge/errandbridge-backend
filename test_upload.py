import requests

with open('test.txt', 'w') as f:
    f.write('hello world')

resp = requests.post(
    'http://localhost:8000/errands/1/attachments',
    headers={'Authorization': 'Bearer devtoken123'},
    files={'file': ('test.txt', open('test.txt', 'rb'))}
)
print("Status code:", resp.status_code)
print("Body:", resp.text)
