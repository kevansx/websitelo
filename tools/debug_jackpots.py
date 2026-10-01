import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv  # noqa: E402

from crm_api import CRMClient, load_crm_config_from_env  # noqa: E402


def main() -> None:
    load_dotenv()
    game_code = (sys.argv[1] if len(sys.argv) > 1 else "megamillions").strip()
    c = CRMClient(load_crm_config_from_env())
    resp = c._request(  # noqa: SLF001
        "GET",
        "/api/v1/jackpots",
        service_key=True,
        params={"configured_only": 1},
        timeout_seconds=30,
    )
    jps = resp.get("jackpots") if isinstance(resp, dict) else None
    if not isinstance(jps, list):
        jps = []
    for jp in jps:
        if not isinstance(jp, dict):
            continue
        if str(jp.get("game_code") or "").strip() == game_code:
            print(json.dumps(jp, indent=2)[:4000])
            return
    print("not found")


if __name__ == "__main__":
    main()

