import json
from dotenv import load_dotenv

load_dotenv()
from crm_api import CRMClient, load_crm_config_from_env

c = CRMClient(load_crm_config_from_env())
rows = c.countries(active_only=0, include_blocked=1).get("countries") or []

blocked = [r for r in rows if r.get("block_website")]
inactive = [r for r in rows if not r.get("is_active")]

print(f"countries: {len(rows)}")
print(f"\nblock_website = true ({len(blocked)}):")
for r in sorted(blocked, key=lambda r: r.get("name") or ""):
    print(f"  {r.get('iso2')}  {r.get('name')}   is_active={r.get('is_active')}")

print(f"\nis_active = false ({len(inactive)}):")
for r in sorted(inactive, key=lambda r: r.get("name") or ""):
    print(f"  {r.get('iso2')}  {r.get('name')}   block_website={r.get('block_website')}")

print("\nMalta row:")
print(json.dumps([r for r in rows if str(r.get("iso2") or "").upper() == "MT"], indent=2))
