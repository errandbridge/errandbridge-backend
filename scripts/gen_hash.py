import sys

sys.path.insert(0, "/app")
from auth import hash_password

hashed = hash_password("Admin123!")
print(hashed)
