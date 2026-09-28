import os
from dotenv import load_dotenv
load_dotenv()
try:
    from supabase import create_client
except ImportError:
    print("supabase not installed")
    exit(1)

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
print(f"URL: {url}")
try:
    sb = create_client(url, key)
    # List buckets
    buckets = sb.storage.list_buckets()
    print("Buckets:")
    for b in buckets:
        print(f" - {b.name}")
except Exception as e:
    print(f"Error: {e}")
