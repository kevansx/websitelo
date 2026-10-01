"""LOCAL PREVIEW ONLY: seed the CRM cache with the CRM's global jackpot feed (captured to
inventory/crm_global_jackpots.json) so CRM_CACHE_ONLY=1 renders real jackpots without a brand key.
Draw times are rolled forward a week at a time so countdowns stay in the future."""
import json, os, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
from crm_cache import CacheConfig, CRMCache

src = Path(__file__).resolve().parents[2] / "inventory" / "crm_global_jackpots.json"
rows = json.loads(src.read_text())
now = datetime.now(timezone.utc)
out = []
for j in rows:
    nd = j.get("next_draw_utc")
    if nd:
        t = datetime.fromisoformat(nd.replace("Z", "")).replace(tzinfo=timezone.utc)
        while t < now:
            t += timedelta(days=7)
        j["cutoff_at_utc"] = t.strftime("%Y-%m-%dT%H:%M:%SZ")
        j["remaining_seconds"] = int((t - now).total_seconds())
    out.append(j)
cache = CRMCache(CacheConfig(db_path=os.environ["CRM_CACHE_DB_PATH"], brand=os.environ.get("WEBSITE_BRAND", "lottosonline")))
cache.upsert_jackpots(out)
cache.set_state("last_jackpots_fetch_at", now.isoformat())
print("seeded", len(out), "jackpots")
