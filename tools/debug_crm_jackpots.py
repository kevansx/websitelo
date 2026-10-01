import os
import sys
import os
import time

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from crm_api import CRMClient, load_crm_config_from_env


def main() -> None:
    cfg = load_crm_config_from_env()
    print("CRM_BASE_URL:", cfg.base_url)
    client = CRMClient(cfg)

    t0 = time.time()
    try:
        data = client._request(
            "GET",
            "/api/v1/jackpots",
            service_key=True,
            params={"configured_only": 1},
            timeout_seconds=30,
        )
    except Exception as e:
        print("ERROR:", type(e).__name__, str(e)[:300])
        print("sec:", round(time.time() - t0, 3))
        return

    print("sec:", round(time.time() - t0, 3))
    print("response_type:", type(data).__name__)
    if isinstance(data, dict):
        print("keys:", sorted(list(data.keys()))[:30])
        jackpots = data.get("jackpots")
        print("jackpots_type:", type(jackpots).__name__)
        if isinstance(jackpots, list):
            print("jackpots_len:", len(jackpots))
            if jackpots:
                first = jackpots[0]
                print("first_type:", type(first).__name__)
                if isinstance(first, dict):
                    sample_keys = sorted(list(first.keys()))
                    print("first_keys_sample:", sample_keys[:40])
                    print("first_game_code:", first.get("game_code"))
                    print("first_currency:", first.get("currency") or (first.get("jackpot") or {}).get("currency"))
                    print("first_jackpot_total:", first.get("jackpot_total") or (first.get("jackpot") or {}).get("amount"))


if __name__ == "__main__":
    main()

