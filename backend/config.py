import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/feed_cleaner.db")
MONTHLY_BUDGET = int(os.getenv("MONTHLY_BUDGET", "10000"))

X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN", "")
X_API_KEY = os.getenv("X_API_KEY", "")
X_API_SECRET = os.getenv("X_API_SECRET", "")

# Scraper (twscrape) configuration
# Format: handle1:pass1:email1:emailpass1,handle2:pass2:email2:emailpass2
SCRAPER_ACCOUNTS = os.getenv("SCRAPER_ACCOUNTS", "")
# scraper_with_fallback | scraper | api
SEARCH_MODE = os.getenv("SEARCH_MODE", "scraper_with_fallback")
