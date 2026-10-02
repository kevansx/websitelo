from __future__ import annotations

import json as jsonlib
import os
from dataclasses import dataclass
from typing import Any

import requests


class CRMError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, payload: Any | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def _debug_safe_json(value: Any) -> Any:
    """Best-effort JSON-safe structure for debug logging."""
    try:
        return jsonlib.loads(jsonlib.dumps(value))
    except Exception:
        return {"_unserializable": str(value)}


@dataclass(frozen=True)
class CRMConfig:
    base_url: str
    service_key: str
    timeout_seconds: int = 25


def load_crm_config_from_env() -> CRMConfig:
    base_url = os.environ.get("CRM_BASE_URL", "").strip().rstrip("/")
    service_key = os.environ.get("CRM_API_SERVICE_KEY", "").strip()
    if not base_url:
        raise RuntimeError("Missing env var CRM_BASE_URL")
    if not service_key:
        raise RuntimeError("Missing env var CRM_API_SERVICE_KEY")
    return CRMConfig(base_url=base_url, service_key=service_key)


class CRMClient:
    def __init__(self, cfg: CRMConfig):
        self.cfg = cfg
        self.session = requests.Session()

    def _headers(self, *, service_key: bool = False, token: str | None = None) -> dict[str, str]:
        h: dict[str, str] = {"Accept": "application/json"}
        if service_key:
            h["X-CRM-API-Key"] = self.cfg.service_key
            # Deterministic brand resolution for shared/global service keys
            # (recommended by the CRM API doc; harmless with per-brand keys).
            brand_slug = os.environ.get("CRM_BRAND_SLUG", "").strip()
            if brand_slug:
                h["X-CRM-Brand-Slug"] = brand_slug
        if token:
            h["Authorization"] = f"Bearer {token}"
        return h

    def _request(
        self,
        method: str,
        path: str,
        *,
        service_key: bool = False,
        token: str | None = None,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        timeout_seconds: int | None = None,
    ) -> Any:
        url = f"{self.cfg.base_url}{path}"
        debug_quotes = (os.environ.get("CRM_QUOTE_DEBUG", "").strip() == "1")
        is_checkout_quote = method.upper() == "POST" and path == "/api/v1/checkout/quote"
        if debug_quotes and is_checkout_quote:
            print(
                "LOTTOEXPRESS REQUEST:",
                jsonlib.dumps(_debug_safe_json(json), ensure_ascii=False),
                flush=True,
            )
        r = self.session.request(
            method,
            url,
            headers=self._headers(service_key=service_key, token=token),
            params=params,
            json=json,
            timeout=int(timeout_seconds) if timeout_seconds is not None else self.cfg.timeout_seconds,
        )
        if debug_quotes and is_checkout_quote:
            try:
                raw_resp: Any = r.json()
            except Exception:
                raw_resp = {"_raw_text": r.text}
            print(
                "LOTTOEXPRESS RESPONSE:",
                jsonlib.dumps(_debug_safe_json(raw_resp), ensure_ascii=False),
                flush=True,
            )

        # Normalize errors into a consistent exception for the Flask app.
        if not r.ok:
            payload = None
            try:
                payload = r.json()
                msg = payload.get("error") or payload.get("message") or r.text
            except Exception:
                msg = r.text
            raise CRMError(f"CRM HTTP {r.status_code}: {msg}", status_code=r.status_code, payload=payload)

        if r.status_code == 204:
            return None
        try:
            return r.json()
        except Exception as e:
            raise CRMError(f"CRM returned non-JSON response: {e}") from e

    # --- Basic endpoints ---
    def health(self) -> Any:
        return self._request("GET", "/api/v1/health")

    # --- Countries ---
    def countries(self, *, active_only: int = 0, include_blocked: int = 1) -> Any:
        return self._request(
            "GET",
            "/api/v1/countries",
            service_key=True,
            params={"active_only": str(int(active_only)), "include_blocked": str(int(include_blocked))},
        )

    # --- Store ---
    def store_games(self) -> Any:
        return self._request("GET", "/api/v1/store/games", service_key=True)

    def store_game(self, game_code: str) -> Any:
        return self._request("GET", f"/api/v1/store/games/{game_code}", service_key=True)

    def store_products(self) -> Any:
        return self._request("GET", "/api/v1/store/products", service_key=True)

    # --- Bundles ---
    def bundle(self, bundle_slug: str) -> Any:
        return self._request("GET", f"/api/v1/bundles/{bundle_slug}", service_key=True)

    # --- Auth ---
    def auth_register(self, payload: dict[str, Any]) -> Any:
        return self._request("POST", "/api/v1/auth/register", service_key=True, json=payload)

    def auth_login(self, payload: dict[str, Any]) -> Any:
        return self._request("POST", "/api/v1/auth/login", service_key=True, json=payload)

    def auth_me(self, token: str) -> Any:
        return self._request("GET", "/api/v1/auth/me", token=token)

    def auth_login_as_customer(
        self, *, audit_id: int | str, token: str, ip: str | None = None
    ) -> Any:
        """
        Trade a staff handoff for a read-only customer bearer token.

        The brand service key signs this, which is why it can only happen here:
        the handoff arrives in a URL the staff browser opened, and the key that
        redeems it must never be within reach of that browser.

        Single-use and good for two minutes, so there is no retrying it and no
        reason to hold onto it - the caller exchanges it on arrival and keeps
        only what comes back.
        """
        payload: dict[str, Any] = {"audit_id": audit_id, "token": str(token)}
        if ip:
            payload["ip"] = str(ip)
        return self._request(
            "POST",
            "/api/v1/auth/login-as/customer",
            service_key=True,
            json=payload,
        )

    def password_reset_request(self, email: str) -> Any:
        # Anti-enumeration: CRM returns success even if email does not exist.
        return self._request(
            "POST",
            "/api/v1/auth/password-reset/request",
            service_key=True,
            json={"email": str(email).strip()},
        )

    def password_reset_confirm(self, *, token: str, new_password: str) -> Any:
        return self._request(
            "POST",
            "/api/v1/auth/password-reset/confirm",
            service_key=True,
            json={"token": str(token), "new_password": str(new_password)},
        )

    def auth_set_password_check(self, token: str) -> Any:
        """
        Whether a set-password token is still good, before we send anyone to the
        form. This is a shortcut for customers the Module created without a
        password, so a dead token means "carry on as normal", not "stop".
        """
        return self._request(
            "POST",
            "/api/v1/auth/set-password/check",
            service_key=True,
            json={"token": str(token)},
        )

    def auth_legacy_signup_check(self, token: str) -> Any:
        """
        The details behind a mail-order customer's invite token.

        Deliberately anti-enumerating: it answers about a token, never about an
        address, so nothing here can be used to ask whether someone is a
        customer. The caller must not undo that by saying more than the CRM did.
        """
        return self._request(
            "POST",
            "/api/v1/auth/legacy-signup/check",
            service_key=True,
            json={"token": str(token)},
        )

    def auth_legacy_signup_claim(self, payload: dict[str, Any]) -> Any:
        """
        Turns an invite into an account, without being told the email address.

        The CRM already holds a verified address for this record and keeps it.
        Registering normally would take one from the form, which is the whole
        difference: the invite proves the address, so nothing the browser sends
        can change who this account belongs to.
        """
        return self._request(
            "POST",
            "/api/v1/auth/legacy-signup/claim",
            service_key=True,
            json=payload,
        )

    def auth_set_password(self, *, token: str, password: str, password_confirm: str) -> Any:
        """Sets the first password on an account and returns a login bearer."""
        return self._request(
            "POST",
            "/api/v1/auth/set-password",
            service_key=True,
            json={"token": str(token), "password": password, "password_confirm": password_confirm},
        )

    def auth_email_verification_request(self, email: str) -> Any:
        return self._request(
            "POST",
            "/api/v1/auth/email-verification/request",
            service_key=True,
            json={"email": str(email).strip()},
        )

    def auth_email_verification_confirm(self, token: str) -> Any:
        return self._request(
            "POST",
            "/api/v1/auth/email-verification/confirm",
            service_key=True,
            json={"token": str(token)},
        )

    # --- Customer profile ---
    def customer_me(self, token: str) -> Any:
        return self._request("GET", "/api/v1/customers/me", token=token)

    def customer_update(self, token: str, payload: dict[str, Any]) -> Any:
        return self._request("PATCH", "/api/v1/customers/me", token=token, json=payload)

    # --- Wallet ---
    def wallet(self, token: str) -> Any:
        return self._request("GET", "/api/v1/wallet", token=token)

    def wallet_transactions(self, token: str, *, page: int = 1, per_page: int = 25) -> Any:
        return self._request(
            "GET",
            "/api/v1/wallet/transactions",
            token=token,
            params={"page": page, "per_page": per_page},
        )

    def wallet_topup_init(self, token: str, payload: dict[str, Any]) -> Any:
        # Some CRM deployments also require service key; the CRM doc says "depends on config".
        return self._request("POST", "/api/v1/wallet/topup/init", token=token, json=payload, service_key=True)

    def wallet_topup_status(self, token: str, intent_id: str) -> Any:
        # Requires bearer token + service key per API contract.
        return self._request("GET", f"/api/v1/wallet/topup/{intent_id}", token=token, service_key=True)

    def winnings_tickets(
        self,
        token: str,
        *,
        page: int = 1,
        per_page: int = 50,
        draw_date_from: str | None = None,
        draw_date_to: str | None = None,
        updated_since: str | None = None,
    ) -> Any:
        params: dict[str, Any] = {"page": int(page), "per_page": int(per_page)}
        if draw_date_from:
            params["draw_date_from"] = draw_date_from
        if draw_date_to:
            params["draw_date_to"] = draw_date_to
        if updated_since:
            params["updated_since"] = updated_since
        return self._request("GET", "/api/v1/winnings/tickets", token=token, params=params)

    # --- Wallet: saved cards (EltroVox direct-card vault) ---
    def wallet_cards(self, token: str) -> Any:
        # Requires bearer token + service key per API.md
        return self._request("GET", "/api/v1/wallet/cards", token=token, service_key=True)

    def wallet_cards_add(self, token: str, payload: dict[str, Any]) -> Any:
        # Requires bearer token + service key per API.md
        return self._request("POST", "/api/v1/wallet/cards", token=token, service_key=True, json=payload)

    def wallet_cards_delete(self, token: str, card_id: int) -> Any:
        # Requires bearer token + service key per API.md
        return self._request("DELETE", f"/api/v1/wallet/cards/{int(card_id)}", token=token, service_key=True)

    def wallet_topup_charge(self, token: str, intent_id: str, payload: dict[str, Any]) -> Any:
        # Requires bearer token + service key per API.md
        return self._request("POST", f"/api/v1/wallet/topup/{intent_id}/charge", token=token, service_key=True, json=payload)

    def wallet_topup_hpp_start(self, token: str, intent_id: str) -> Any:
        # Requires bearer token + service key per API.md
        return self._request("POST", f"/api/v1/wallet/topup/{intent_id}/hpp/start", token=token, service_key=True)

    # --- Wallet: emailed payment links ---
    # A customer follows these from an email and is usually not logged in, so
    # there is no bearer to send and the service key alone authenticates. That
    # is also why every one of these calls has to be made from the server: the
    # key would be readable by anyone if the browser made them.

    def wallet_topup_email_link_context(self, link_token: str) -> Any:
        """
        What an emailed payment link is for, without starting anything.

        Deliberately separate from starting the payment. Some providers issue
        a short-lived session the moment they are contacted, so opening the
        email must not contact them - the customer may read the mail hours
        before paying, and the session would be dead by the time they clicked.
        """
        return self._request(
            "POST",
            "/api/v1/wallet/topup/email-link/context",
            service_key=True,
            json={"token": str(link_token)},
        )

    def wallet_topup_email_link_hpp_start(self, payload: dict[str, Any]) -> Any:
        """
        Starts the provider session for an emailed link. Called on Pay Now only.

        The payload may carry identity fields a provider demands of the payer
        (Bitolo wants a Mexican RFC and CURP). They pass straight through to
        the CRM and are not kept, logged or echoed anywhere by us.
        """
        return self._request(
            "POST",
            "/api/v1/wallet/topup/email-link/hpp/start",
            service_key=True,
            json=payload,
        )

    def wallet_topup_email_link_status(self, link_token: str) -> Any:
        """
        Where an emailed link's payment has got to.

        `GET /wallet/topup/<intent_id>` answers the same question but wants a
        customer bearer, which this journey by definition does not have.
        """
        return self._request(
            "POST",
            "/api/v1/wallet/topup/email-link/status",
            service_key=True,
            json={"token": str(link_token)},
        )

    def wallet_topup_emerchant_3ds_method_continue(self, token: str, intent_id: str) -> Any:
        # Emerchant direct-card 3DSv2 method continuation.
        # Requires bearer token + service key per API.md.
        return self._request(
            "POST",
            f"/api/v1/wallet/topup/{intent_id}/emerchant/3ds/method/continue",
            token=token,
            service_key=True,
        )

    # --- Orders ---
    def orders(self, token: str, *, page: int = 1, per_page: int = 25) -> Any:
        return self._request("GET", "/api/v1/orders", token=token, params={"page": page, "per_page": per_page})

    def order(self, token: str, order_id: int) -> Any:
        return self._request("GET", f"/api/v1/orders/{order_id}", token=token)

    # --- Legacy orders (read-only imported history; kept separate from current orders) ---
    def legacy_orders(self, token: str, *, page: int = 1, per_page: int = 25) -> Any:
        return self._request("GET", "/api/v1/legacy-orders", token=token, params={"page": page, "per_page": per_page})

    def legacy_order(self, token: str, legacy_order_id: str) -> Any:
        return self._request("GET", f"/api/v1/legacy-orders/{legacy_order_id}", token=token)

    # --- Checkout ---
    def checkout_quote(self, payload: dict[str, Any], *, token: str | None = None, service_key: bool = False) -> Any:
        return self._request("POST", "/api/v1/checkout/quote", token=token, service_key=service_key, json=payload)

    def checkout(self, token: str, payload: dict[str, Any]) -> Any:
        # Note: insufficient balance may return 402 which our `_request` will treat as error.
        return self._request("POST", "/api/v1/checkout", token=token, json=payload)

    def checkout_submit(self, token: str, *, quote_id: int | str, use_wins: bool = False) -> Any:
        # Quote ids are echoed back as the CRM issued them: coercing to int drops
        # tenants that issue non-numeric ids, and that failure used to be
        # indistinguishable from "submit is unsupported here".
        qid: int | str = quote_id
        if isinstance(qid, str) and qid.strip().lstrip("-").isdigit():
            qid = int(qid.strip())
        payload: dict[str, Any] = {"quote_id": qid}
        # Authorisation to spend winnings, and only ever because the customer
        # gave it. The CRM defaults this to false and so does this method: the
        # flag is omitted entirely unless it is true, so a caller that knows
        # nothing about winnings cannot accidentally spend them.
        if use_wins:
            payload["use_wins"] = True
        return self._request("POST", "/api/v1/checkout/submit", token=token, json=payload)

    # --- Syndicate subscriptions (CRM reply, 2 Oct 2026; same API Live Lottos uses) ---
    # Join: checkout(token, {"saved_card_id", "items": [{"kind": "syndicate", "ticket_mode": "subscription",
    # "product_code", "shares"}]}). Billed at subscription_standard_price_cents per share, weekly.
    def subscriptions(self, token: str) -> Any:
        return self._request("GET", "/api/v1/subscriptions", token=token, service_key=True)

    def subscription_pause(self, token: str, subscription_id: int | str, weeks: int | None = None) -> Any:
        """Pause for 1-12 weeks (the CRM's default is 4). Only an active membership can pause."""
        body = {"weeks": int(weeks)} if weeks else {}
        return self._request("POST", f"/api/v1/subscriptions/{subscription_id}/pause", token=token, service_key=True, json=body)

    def subscription_resume(self, token: str, subscription_id: int | str) -> Any:
        return self._request("POST", f"/api/v1/subscriptions/{subscription_id}/resume", token=token, service_key=True, json={})

    def subscription_cancel(self, token: str, subscription_id: int | str, payload: dict[str, Any] | None = None) -> Any:
        return self._request("POST", f"/api/v1/subscriptions/{subscription_id}/cancel", token=token, service_key=True,
                             json=payload or {})

    def subscriptions_due(self, *, next_charge_after: str | None = None, next_charge_before: str | None = None) -> Any:
        """Service key, no customer token: the brand's memberships whose next charge falls in the window (each with
        email, next_amount_cents, last_charge_at/status). Drives the renewal reminder and receipt emails."""
        params = {k: v for k, v in {"next_charge_after": next_charge_after, "next_charge_before": next_charge_before}.items() if v}
        return self._request("GET", "/api/v1/subscriptions", service_key=True, params=params)

    # --- Results sync ---
    def draw_results(
        self,
        *,
        game_code: str | None = None,
        status: str = "completed",
        draw_date_from: str | None = None,
        draw_date_to: str | None = None,
        include_prize_tiers: int = 0,
        updated_since: str | None = None,
        cursor: str | None = None,
        limit: int = 200,
    ) -> Any:
        params: dict[str, Any] = {
            "status": status,
            "include_prize_tiers": include_prize_tiers,
            "limit": limit,
        }
        if game_code:
            params["game_code"] = game_code
        if draw_date_from:
            params["draw_date_from"] = draw_date_from
        if draw_date_to:
            params["draw_date_to"] = draw_date_to
        if updated_since:
            params["updated_since"] = updated_since
        if cursor:
            params["cursor"] = cursor
        return self._request("GET", "/api/v1/draw-results", service_key=True, params=params)

    # --- Marketing Module surfaces (banners + events) ---
    def marketing_banners(self, placement: str, *, token: str | None = None) -> Any:
        # Token is optional; when provided CRM can return logged-in targeting.
        return self._request(
            "GET",
            "/api/v1/marketing/banners",
            service_key=True,
            token=token,
            params={"placement": placement},
        )

    def marketing_events(self, payload: dict[str, Any], *, token: str | None = None) -> Any:
        # Events are brand-scoped; token is optional to associate to a customer.
        return self._request(
            "POST",
            "/api/v1/marketing/events",
            service_key=True,
            token=token,
            json=payload,
        )

