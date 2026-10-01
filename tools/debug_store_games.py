import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv  # noqa: E402

from crm_api import CRMClient, load_crm_config_from_env  # noqa: E402


def main() -> None:
    load_dotenv()
    c = CRMClient(load_crm_config_from_env())
    resp = c.store_games()
    games = resp.get("games") if isinstance(resp, dict) else None
    if not isinstance(games, list):
        games = []
    for g in games:
        if not isinstance(g, dict):
            continue
        print(g.get("game_code"), "-", g.get("game_name"))


if __name__ == "__main__":
    main()

