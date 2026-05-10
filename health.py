import httpx
import os
from dotenv import load_dotenv

load_dotenv()

token = os.getenv("X_BEARER_TOKEN")

if not token:
    print("ERROR: X_BEARER_TOKEN not found in .env")
    exit(1)

if not token.startswith("AAAA"):
    print(f"WARNING: Token format looks wrong (expected AAAA..., got {token[:4]}...)")

response = httpx.get(
    "https://api.twitter.com/2/tweets/search/recent",
    params={"query": "test", "max_results": 10},
    headers={"Authorization": f"Bearer {token}"},
)

print(f"HTTP Status: {response.status_code}")

if response.status_code == 200:
    data = response.json()
    count = len(data.get("data", []))
    print(f"Auth valid — got {count} tweets back")

elif response.status_code == 401:
    print("Auth FAILED — token invalid or not activated")
    print(response.json())

elif response.status_code == 403:
    print("Auth valid but endpoint access denied — check app permissions in dev console")
    print(response.json())

elif response.status_code == 429:
    print("Auth valid — rate limited")

else:
    print(f"Unexpected response:")
    print(response.text)