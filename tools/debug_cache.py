import json
import os
import sqlite3


def main() -> None:
    db_path = os.environ.get("CRM_CACHE_DB_PATH", "./data/crm_cache.sqlite")
    print("CRM_CACHE_DB_PATH:", db_path)
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM jackpots")
        print("jackpots rows:", cur.fetchone()[0])
    except Exception as e:
        print("jackpots table error:", e)
        return

    cur.execute("SELECT game_code, raw_json FROM jackpots ORDER BY game_code ASC LIMIT 5")
    rows = cur.fetchall()
    for game_code, raw_json in rows:
        try:
            obj = json.loads(raw_json)
        except Exception:
            obj = {"raw_json": raw_json[:200]}
        print("\n---", game_code, "---")
        for k in ("game_code", "game_name", "currency", "jackpot_total", "remaining_seconds", "cutoff_at_utc", "status"):
            if k in obj:
                print(f"{k}:", obj.get(k))
        if "jackpot" in obj:
            print("jackpot:", obj.get("jackpot"))


if __name__ == "__main__":
    main()

