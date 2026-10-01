from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any
from typing import Iterable


@dataclass(frozen=True)
class CacheConfig:
    db_path: str
    brand: str


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def _to_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return None


class CRMCache:
    """SQLite-backed cache for CRM data with idempotent upserts (Winnow pattern)."""

    def __init__(self, cfg: CacheConfig):
        self.cfg = cfg
        self._lock = threading.Lock()
        self.init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.cfg.db_path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def init_db(self) -> None:
        parent = os.path.dirname(self.cfg.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jackpots (
                    brand TEXT NOT NULL,
                    game_code TEXT NOT NULL,
                    game_name TEXT,
                    currency TEXT,
                    jackpot_total REAL,
                    draw_date TEXT,
                    cutoff_at_utc TEXT,
                    rollover TEXT,
                    remaining_seconds INTEGER,
                    fetched_at TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    PRIMARY KEY (brand, game_code)
                );
                CREATE TABLE IF NOT EXISTS draw_results (
                    id TEXT PRIMARY KEY,
                    game_code TEXT NOT NULL,
                    draw_date TEXT,
                    draw_number TEXT,
                    draw_datetime_utc TEXT,
                    status TEXT,
                    currency TEXT,
                    jackpot_total REAL,
                    numbers_json TEXT,
                    updated_at TEXT,
                    fetched_at TEXT NOT NULL,
                    raw_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS draw_prize_tiers (
                    draw_id TEXT NOT NULL,
                    tier_code TEXT NOT NULL,
                    currency TEXT,
                    prize_amount REAL,
                    winners_count INTEGER,
                    raw_json TEXT,
                    PRIMARY KEY (draw_id, tier_code),
                    FOREIGN KEY (draw_id) REFERENCES draw_results(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS sync_state (
                    k TEXT PRIMARY KEY,
                    v TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS countries (
                    brand TEXT NOT NULL,
                    iso2 TEXT NOT NULL,
                    name TEXT,
                    iso3 TEXT,
                    dialing_prefix TEXT,
                    is_active INTEGER,
                    soft_block INTEGER,
                    block_website INTEGER,
                    fetched_at TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    PRIMARY KEY (brand, iso2)
                );
                CREATE TABLE IF NOT EXISTS website_policies (
                    brand TEXT NOT NULL,
                    category TEXT NOT NULL,
                    policy_name TEXT NOT NULL,
                    value_int INTEGER,
                    comment TEXT,
                    fetched_at TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    PRIMARY KEY (brand, category, policy_name)
                );
                CREATE TABLE IF NOT EXISTS github_pull_settings (
                    brand TEXT PRIMARY KEY,
                    github_user TEXT,
                    github_key_enc TEXT,
                    command_template TEXT,
                    updated_at TEXT NOT NULL
                );
                -- Account creations, for rate limiting. Here rather than in
                -- process memory because the site runs two gunicorn workers,
                -- and a limit each worker counts on its own is half a limit.
                CREATE TABLE IF NOT EXISTS signup_attempts (
                    ip TEXT NOT NULL,
                    at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_signup_attempts_ip_at
                    ON signup_attempts(ip, at);
                """
            )
            # `countries` predates soft_block, and CREATE TABLE IF NOT EXISTS
            # leaves an existing table alone, so a deployed cache needs the
            # column adding rather than the table creating.
            existing = {r["name"] for r in conn.execute("PRAGMA table_info(countries)").fetchall()}
            if "soft_block" not in existing:
                conn.execute("ALTER TABLE countries ADD COLUMN soft_block INTEGER")
            conn.commit()

    # --- sign-up rate limiting ---
    def record_signup_attempt(self, ip: str, *, at: float) -> None:
        with self._connect() as conn:
            conn.execute("INSERT INTO signup_attempts(ip, at) VALUES(?,?)", (ip, float(at)))
            conn.commit()

    def count_signup_attempts(self, ip: str, *, since: float) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM signup_attempts WHERE ip = ? AND at >= ?",
                (ip, float(since)),
            ).fetchone()
            return int(row["n"] if row else 0)

    def prune_signup_attempts(self, *, before: float) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM signup_attempts WHERE at < ?", (float(before),))
            conn.commit()

    # --- sync state ---
    def get_state(self, k: str, default: str | None = None) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT v FROM sync_state WHERE k = ?", (k,)).fetchone()
            if not row:
                return default
            return row["v"]

    def set_state(self, k: str, v: str | None) -> None:
        now = _utcnow_iso()
        with self._connect() as conn:
            self._set_state(conn, k, v, now=now)
            conn.commit()

    def _set_state(self, conn: sqlite3.Connection, k: str, v: str | None, *, now: str | None = None) -> None:
        ts = now or _utcnow_iso()
        conn.execute(
            "INSERT INTO sync_state(k, v, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(k) DO UPDATE SET v=excluded.v, updated_at=excluded.updated_at",
            (k, v, ts),
        )

    # --- DB-backed lock (simple TTL lock stored in sync_state) ---
    def try_acquire_lock(self, name: str, *, ttl_seconds: int = 300) -> bool:
        """
        Best-effort process lock backed by SQLite.
        Stores JSON like {"expires_at": "...Z"} in sync_state under key "lock:<name>".
        """
        key = f"lock:{name}"
        now = datetime.now(timezone.utc)
        expires_at = datetime.fromtimestamp(now.timestamp() + ttl_seconds, tz=timezone.utc)
        payload = json.dumps({"expires_at": expires_at.isoformat().replace("+00:00", "Z")})

        with self._lock:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT v FROM sync_state WHERE k = ?", (key,)).fetchone()
                if row and row["v"]:
                    try:
                        cur = json.loads(row["v"])
                        exp = cur.get("expires_at")
                        if exp:
                            exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                            if exp_dt > now:
                                conn.execute("ROLLBACK")
                                return False
                    except Exception:
                        # treat as expired/invalid and take lock
                        pass
                conn.execute(
                    "INSERT INTO sync_state(k, v, updated_at) VALUES(?,?,?) "
                    "ON CONFLICT(k) DO UPDATE SET v=excluded.v, updated_at=excluded.updated_at",
                    (key, payload, _utcnow_iso()),
                )
                conn.commit()
                return True

    def release_lock(self, name: str) -> None:
        key = f"lock:{name}"
        with contextlib.suppress(Exception):
            with self._connect() as conn:
                conn.execute("DELETE FROM sync_state WHERE k = ?", (key,))
                conn.commit()

    # --- jackpots ---
    def upsert_jackpots(self, jackpots: Iterable[dict[str, Any]]) -> None:
        now = _utcnow_iso()
        with self._connect() as conn:
            for jp in jackpots:
                if not isinstance(jp, dict):
                    continue
                game_code = str(jp.get("game_code") or "").strip()
                if not game_code:
                    continue
                conn.execute(
                    """
                    INSERT INTO jackpots(
                        brand, game_code, game_name, currency, jackpot_total,
                        draw_date, cutoff_at_utc, rollover, remaining_seconds,
                        fetched_at, raw_json
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(brand, game_code) DO UPDATE SET
                        game_name=excluded.game_name,
                        currency=excluded.currency,
                        jackpot_total=excluded.jackpot_total,
                        draw_date=excluded.draw_date,
                        cutoff_at_utc=excluded.cutoff_at_utc,
                        rollover=excluded.rollover,
                        remaining_seconds=excluded.remaining_seconds,
                        fetched_at=excluded.fetched_at,
                        raw_json=excluded.raw_json
                    """,
                    (
                        self.cfg.brand,
                        game_code,
                        jp.get("game_name"),
                        jp.get("currency"),
                        _to_float(jp.get("jackpot_total") or (jp.get("jackpot") or {}).get("amount")),
                        jp.get("draw_date"),
                        jp.get("cutoff_at_utc") or jp.get("next_draw_utc"),
                        jp.get("rollover"),
                        _to_int(jp.get("remaining_seconds")),
                        now,
                        json.dumps(jp, ensure_ascii=False),
                    ),
                )
            # IMPORTANT: update sync_state using the same connection to avoid SQLITE_BUSY locks.
            self._set_state(conn, "last_jackpots_fetch_at", now, now=now)
            conn.commit()

    def get_cached_jackpots(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT raw_json FROM jackpots WHERE brand = ? ORDER BY game_code ASC",
                (self.cfg.brand,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                out.append(json.loads(r["raw_json"]))
            except Exception:
                continue
        return out

    # --- draw results ---
    def upsert_draw_results_page(self, draws: Iterable[dict[str, Any]], *, include_prize_tiers: bool = True) -> None:
        now = _utcnow_iso()
        with self._connect() as conn:
            for d in draws:
                if not isinstance(d, dict):
                    continue
                draw_id = str(d.get("id") or "").strip()
                game_code = str(d.get("game_code") or "").strip()
                if not draw_id or not game_code:
                    continue

                numbers_json = None
                if isinstance(d.get("numbers"), dict):
                    numbers_json = json.dumps(d.get("numbers"), ensure_ascii=False)

                conn.execute(
                    """
                    INSERT INTO draw_results(
                        id, game_code, draw_date, draw_number, draw_datetime_utc,
                        status, currency, jackpot_total, numbers_json, updated_at,
                        fetched_at, raw_json
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        game_code=excluded.game_code,
                        draw_date=excluded.draw_date,
                        draw_number=excluded.draw_number,
                        draw_datetime_utc=excluded.draw_datetime_utc,
                        status=excluded.status,
                        currency=excluded.currency,
                        jackpot_total=excluded.jackpot_total,
                        numbers_json=excluded.numbers_json,
                        updated_at=excluded.updated_at,
                        fetched_at=excluded.fetched_at,
                        raw_json=excluded.raw_json
                    """,
                    (
                        draw_id,
                        game_code,
                        d.get("draw_date"),
                        d.get("draw_number"),
                        d.get("draw_datetime_utc"),
                        d.get("status"),
                        d.get("currency"),
                        _to_float(d.get("jackpot_total")),
                        numbers_json,
                        d.get("updated_at"),
                        now,
                        json.dumps(d, ensure_ascii=False),
                    ),
                )

                if include_prize_tiers and isinstance(d.get("prize_tiers"), list):
                    for t in d.get("prize_tiers") or []:
                        if not isinstance(t, dict):
                            continue
                        tier_code = str(t.get("tier_code") or t.get("code") or "").strip()
                        if not tier_code:
                            continue
                        conn.execute(
                            """
                            INSERT INTO draw_prize_tiers(
                                draw_id, tier_code, currency, prize_amount, winners_count, raw_json
                            )
                            VALUES(?, ?, ?, ?, ?, ?)
                            ON CONFLICT(draw_id, tier_code) DO UPDATE SET
                                currency=excluded.currency,
                                prize_amount=excluded.prize_amount,
                                winners_count=excluded.winners_count,
                                raw_json=excluded.raw_json
                            """,
                            (
                                draw_id,
                                tier_code,
                                t.get("currency"),
                                _to_float(t.get("prize_amount") or t.get("amount")),
                                _to_int(t.get("winners_count") or t.get("winners")),
                                json.dumps(t, ensure_ascii=False),
                            ),
                        )
            conn.commit()

    def get_draw_results_for_game(self, game_code: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT raw_json
                FROM draw_results
                WHERE game_code = ?
                ORDER BY draw_date DESC, id DESC
                LIMIT ?
                """,
                (game_code, int(limit)),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                out.append(json.loads(r["raw_json"]))
            except Exception:
                continue
        return out

    # --- countries ---
    def upsert_countries(self, countries: Iterable[dict[str, Any]]) -> None:
        now = _utcnow_iso()
        with self._connect() as conn:
            for c in countries:
                if not isinstance(c, dict):
                    continue
                iso2 = str(c.get("iso2") or "").strip().upper()
                if not iso2:
                    continue
                conn.execute(
                    """
                    INSERT INTO countries(
                        brand, iso2, name, iso3, dialing_prefix,
                        is_active, soft_block, block_website,
                        fetched_at, raw_json
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(brand, iso2) DO UPDATE SET
                        name=excluded.name,
                        iso3=excluded.iso3,
                        dialing_prefix=excluded.dialing_prefix,
                        is_active=excluded.is_active,
                        soft_block=excluded.soft_block,
                        block_website=excluded.block_website,
                        fetched_at=excluded.fetched_at,
                        raw_json=excluded.raw_json
                    """,
                    (
                        self.cfg.brand,
                        iso2,
                        c.get("name"),
                        c.get("iso3"),
                        c.get("dialing_prefix"),
                        # `active` is accepted alongside `is_active` because
                        # the column drives every country dropdown on the site,
                        # and a renamed field would empty all of them.
                        1 if bool(c.get("is_active") if c.get("is_active") is not None else c.get("active")) else 0,
                        1 if bool(c.get("soft_block")) else 0,
                        1 if bool(c.get("block_website")) else 0,
                        now,
                        json.dumps(c, ensure_ascii=False),
                    ),
                )
            self._set_state(conn, "last_countries_fetch_at", now, now=now)
            conn.commit()

    def get_country(self, iso2: str) -> dict[str, Any] | None:
        code = (iso2 or "").strip().upper()
        if not code:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT raw_json FROM countries WHERE brand = ? AND iso2 = ?",
                (self.cfg.brand, code),
            ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row["raw_json"])
        except Exception:
            return None

    def is_country_blocked_for_website(self, iso2: str) -> bool | None:
        """
        Returns:
          - True/False if we have cached info
          - None if country is not present in cache
        """
        c = self.get_country(iso2)
        if not isinstance(c, dict):
            return None
        return bool(c.get("block_website"))

    def is_country_active(self, iso2: str) -> bool | None:
        """
        Returns:
          - True/False if we have cached info
          - None if country is not present in cache
        """
        c = self.get_country(iso2)
        if not isinstance(c, dict):
            return None
        return bool(c.get("is_active"))

    def country_restriction(self, iso2: str) -> str:
        """
        Which of the CRM's three website modes a country is in.

        - `active`        browse, register and play
        - `soft_block`    browse and play, but no new registrations
        - `block_website` no access to the site at all
        - `unknown`       nothing for the site to enforce

        Soft block is read from its own flag. It used to be inferred from
        `is_active = 0`, and that inference is wrong now the flag exists.

        A row carrying no readable active flag is `unknown` rather than
        blocked. An inactive country does close the site, so reading a flag we
        could not find as "inactive" would turn a renamed field in the
        countries payload into a total outage, with every visitor on earth
        meeting the blocked page at once.
        """
        c = self.get_country(iso2)
        if not isinstance(c, dict):
            return "unknown"
        if bool(c.get("block_website")):
            return "block_website"
        active = c.get("is_active")
        if active is None:
            active = c.get("active")
        if active is None:
            return "unknown"
        if bool(active):
            return "soft_block" if bool(c.get("soft_block")) else "active"
        return "block_website"

    def get_countries(self, *, active_only: bool = True, include_blocked: bool = False) -> list[dict[str, Any]]:
        """
        Returns cached country rows as raw CRM-shaped dicts.
        """
        where = ["brand = ?"]
        params: list[Any] = [self.cfg.brand]
        if active_only:
            where.append("COALESCE(is_active, 0) = 1")
        if not include_blocked:
            where.append("COALESCE(block_website, 0) = 0")

        q = "SELECT raw_json FROM countries WHERE " + " AND ".join(where) + " ORDER BY name ASC"
        with self._connect() as conn:
            rows = conn.execute(q, tuple(params)).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                v = json.loads(r["raw_json"])
                if isinstance(v, dict):
                    out.append(v)
            except Exception:
                continue
        return out

    # --- admin status helpers ---
    def get_sync_status(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute("SELECT k, v, updated_at FROM sync_state").fetchall()
        return {r["k"]: {"v": r["v"], "updated_at": r["updated_at"]} for r in rows}

    def counts(self) -> dict[str, int]:
        tables = [
            "jackpots",
            "draw_results",
            "draw_prize_tiers",
            "website_policies",
            "countries",
            "github_pull_settings",
        ]
        out: dict[str, int] = {}
        with self._connect() as conn:
            for t in tables:
                try:
                    row = conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()
                    out[t] = int((row["n"] if row else 0) or 0)
                except Exception:
                    out[t] = 0
        return out    # --- github pull settings ---
    def get_github_pull_settings(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT github_user, github_key_enc, command_template, updated_at FROM github_pull_settings WHERE brand = ?",
                (self.cfg.brand,),
            ).fetchone()
        if not row:
            return {}
        return {
            "github_user": row["github_user"],
            "github_key_enc": row["github_key_enc"],
            "command_template": row["command_template"],
            "updated_at": row["updated_at"],
        }

    def upsert_github_pull_settings(
        self,
        *,
        github_user: str | None = None,
        github_key_enc: str | None = None,
        command_template: str | None = None,
    ) -> None:
        now = _utcnow_iso()
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT github_user, github_key_enc, command_template FROM github_pull_settings WHERE brand = ?",
                (self.cfg.brand,),
            ).fetchone()
            cur_user = cur["github_user"] if cur else None
            cur_key = cur["github_key_enc"] if cur else None
            cur_tpl = cur["command_template"] if cur else None
            conn.execute(
                """
                INSERT INTO github_pull_settings(brand, github_user, github_key_enc, command_template, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(brand) DO UPDATE SET
                    github_user=excluded.github_user,
                    github_key_enc=excluded.github_key_enc,
                    command_template=excluded.command_template,
                    updated_at=excluded.updated_at
                """,
                (
                    self.cfg.brand,
                    github_user if github_user is not None else cur_user,
                    github_key_enc if github_key_enc is not None else cur_key,
                    command_template if command_template is not None else cur_tpl,
                    now,
                ),
            )
            conn.commit()

    # --- website policies ---
    def upsert_website_policies(self, policies_by_category: dict[str, Any]) -> int:
        now = _utcnow_iso()
        if not isinstance(policies_by_category, dict):
            policies_by_category = {}
        n = 0
        with self._connect() as conn:
            for cat, policies in policies_by_category.items():
                category = str(cat or "").strip()
                if not category or not isinstance(policies, dict):
                    continue
                for name, pobj in policies.items():
                    policy_name = str(name or "").strip()
                    if not policy_name:
                        continue
                    if not isinstance(pobj, dict):
                        pobj = {"value_int": pobj}
                    value_int = _to_int(pobj.get("value_int"))
                    comment = pobj.get("comment")
                    conn.execute(
                        """
                        INSERT INTO website_policies(
                            brand, category, policy_name, value_int, comment, fetched_at, raw_json
                        )
                        VALUES(?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(brand, category, policy_name) DO UPDATE SET
                            value_int=excluded.value_int,
                            comment=excluded.comment,
                            fetched_at=excluded.fetched_at,
                            raw_json=excluded.raw_json
                        """,
                        (
                            self.cfg.brand,
                            category,
                            policy_name,
                            value_int,
                            str(comment) if comment is not None else None,
                            now,
                            json.dumps(pobj, ensure_ascii=False),
                        ),
                    )
                    n += 1
            self._set_state(conn, "last_website_policies_fetch_at", now, now=now)
            conn.commit()
        return n

    def get_website_policies_grouped(self) -> dict[str, list[dict[str, Any]]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT category, policy_name, value_int, comment
                FROM website_policies
                WHERE brand = ?
                ORDER BY category ASC, policy_name ASC
                """,
                (self.cfg.brand,),
            ).fetchall()
        out: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            cat = str(r["category"] or "").strip() or "other"
            out.setdefault(cat, []).append(
                {
                    "name": r["policy_name"],
                    "value_int": r["value_int"],
                    "comment": r["comment"],
                }
            )
        return out
