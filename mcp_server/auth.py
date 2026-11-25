"""OAuth 2.1 provider, credential management, and raw ASGI auth middleware."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from starlette.types import ASGIApp, Receive, Scope, Send


@dataclass(frozen=True)
class OAuthCredentials:
    client_id: str
    client_secret: str
    static_token: str | None = None


def _parse_env_file(env_path: Path) -> dict[str, str]:
    """Parse KEY=VALUE pairs from a `.env` file."""
    if not env_path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        cleaned = value.strip().strip('"').strip("'")
        if cleaned:
            values[key.strip()] = cleaned
    return values


def _append_env_vars(env_path: Path, updates: dict[str, str]) -> None:
    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    prefix = "" if (not existing or existing.endswith("\n")) else "\n"
    lines = "".join(f"{k}={v}\n" for k, v in updates.items())
    env_path.write_text(f"{existing}{prefix}{lines}", encoding="utf-8")
    try:
        os.chmod(env_path, 0o600)
    except OSError:
        pass


def load_or_create_oauth_credentials(
    root_dir: Path, script_dir: Path | None = None
) -> tuple[OAuthCredentials, Path, bool]:
    """Load `MCP_CLIENT_ID` and `MCP_CLIENT_SECRET` from `.env`, or generate them.

    Returns:
        `(credentials, env_file_path, was_created)`
    """
    target_env = root_dir / ".env"
    target_vals = _parse_env_file(target_env)

    if "MCP_CLIENT_ID" in target_vals and "MCP_CLIENT_SECRET" in target_vals:
        return (
            OAuthCredentials(
                client_id=target_vals["MCP_CLIENT_ID"],
                client_secret=target_vals["MCP_CLIENT_SECRET"],
                static_token=target_vals.get("MCP_AUTH_TOKEN"),
            ),
            target_env,
            False,
        )

    if script_dir is not None:
        script_env = script_dir / ".env"
        if script_env.resolve() != target_env.resolve():
            script_vals = _parse_env_file(script_env)
            if "MCP_CLIENT_ID" in script_vals and "MCP_CLIENT_SECRET" in script_vals:
                return (
                    OAuthCredentials(
                        client_id=script_vals["MCP_CLIENT_ID"],
                        client_secret=script_vals["MCP_CLIENT_SECRET"],
                        static_token=script_vals.get("MCP_AUTH_TOKEN"),
                    ),
                    script_env,
                    False,
                )

    client_id = target_vals.get("MCP_CLIENT_ID") or f"mcp_{secrets.token_urlsafe(16)}"
    client_secret = target_vals.get("MCP_CLIENT_SECRET") or secrets.token_urlsafe(32)

    to_write: dict[str, str] = {}
    if "MCP_CLIENT_ID" not in target_vals:
        to_write["MCP_CLIENT_ID"] = client_id
    if "MCP_CLIENT_SECRET" not in target_vals:
        to_write["MCP_CLIENT_SECRET"] = client_secret

    if to_write:
        _append_env_vars(target_env, to_write)

    return (
        OAuthCredentials(
            client_id=client_id,
            client_secret=client_secret,
            static_token=target_vals.get("MCP_AUTH_TOKEN"),
        ),
        target_env,
        bool(to_write),
    )


def _get_header(scope: Scope, name: bytes) -> str:
    for k, v in scope.get("headers", ()):
        if k.lower() == name:
            return v.decode("latin-1").strip()
    return ""


def _get_base_url(scope: Scope) -> str:
    """Reconstruct external base URL, respecting reverse proxy / tunnel headers."""
    proto = _get_header(scope, b"x-forwarded-proto") or scope.get("scheme", "http")
    proto = proto.split(",")[0].strip()
    host = _get_header(scope, b"x-forwarded-host") or _get_header(scope, b"host")
    host = host.split(",")[0].strip()
    if not host:
        server = scope.get("server")
        host = f"{server[0]}:{server[1]}" if server else "127.0.0.1:8000"
    return f"{proto}://{host}"


async def _read_body(receive: Receive) -> bytes:
    chunks: list[bytes] = []
    while True:
        message = await receive()
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


async def _send_json(
    send: Send,
    status: int,
    payload: dict,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    body = json.dumps(payload).encode("utf-8")
    headers: list[tuple[bytes, bytes]] = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cache-control", b"no-store"),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


async def _send_redirect(send: Send, location: str) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 302,
            "headers": [
                (b"location", location.encode("utf-8")),
                (b"content-length", b"0"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": b""})


def _verify_pkce(verifier: str, challenge: str, method: str) -> bool:
    if method == "S256":
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return hmac.compare_digest(computed, challenge)
    if method == "plain":
        return hmac.compare_digest(verifier, challenge)
    return False


class OAuthMiddleware:
    """Raw ASGI middleware providing OAuth 2.1 endpoints and Bearer protection."""

    def __init__(
        self,
        app: ASGIApp,
        credentials: OAuthCredentials,
        token_store_path: Path | None = None,
    ) -> None:
        self.app = app
        self._creds = credentials
        self._token_store_path = token_store_path
        self._auth_codes: dict[str, dict] = {}
        self._access_tokens: dict[str, float] = {}
        self._refresh_tokens: set[str] = set()
        self._load_tokens()

    def _load_tokens(self) -> None:
        if self._token_store_path is None or not self._token_store_path.is_file():
            return
        try:
            data = json.loads(self._token_store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        now = time.time()
        raw_access = data.get("access_tokens")
        if isinstance(raw_access, dict):
            for tok, exp in raw_access.items():
                if isinstance(tok, str) and isinstance(exp, (int, float)) and exp > now:
                    self._access_tokens[tok] = float(exp)

        raw_refresh = data.get("refresh_tokens")
        if isinstance(raw_refresh, list):
            self._refresh_tokens = {tok for tok in raw_refresh if isinstance(tok, str)}

    def _save_tokens(self) -> None:
        if self._token_store_path is None:
            return
        now = time.time()
        active_access = {
            tok: exp for tok, exp in self._access_tokens.items() if exp > now
        }
        payload = {
            "access_tokens": active_access,
            "refresh_tokens": sorted(self._refresh_tokens),
        }
        self._token_store_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._token_store_path.with_suffix(
            f"{self._token_store_path.suffix}.tmp.{os.getpid()}"
        )
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp_path, 0o600)
        except OSError:
            pass
        os.replace(tmp_path, self._token_store_path)

    def _issue_tokens(self) -> dict:
        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(32)
        expires_in = 86400  # 24 hours
        self._access_tokens[access_token] = time.time() + expires_in
        self._refresh_tokens.add(refresh_token)
        self._save_tokens()
        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": expires_in,
            "refresh_token": refresh_token,
        }

    def _is_valid_bearer(self, token: str) -> bool:
        if self._creds.static_token and hmac.compare_digest(token, self._creds.static_token):
            return True
        now = time.time()
        expiry = self._access_tokens.get(token)
        if expiry is not None and expiry > now:
            return True
        if expiry is not None:
            self._access_tokens.pop(token, None)
            self._save_tokens()
        return False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()
        base_url = _get_base_url(scope)

        # 1. OAuth Protected Resource Metadata (RFC 9728)
        if method == "GET" and path in (
            "/.well-known/oauth-protected-resource",
            "/.well-known/oauth-protected-resource/mcp",
        ):
            await _send_json(
                send,
                200,
                {
                    "resource": f"{base_url}/mcp",
                    "authorization_servers": [base_url],
                    "bearer_methods_supported": ["header"],
                },
            )
            return

        # 2. OAuth Authorization Server Metadata (RFC 8414)
        if method == "GET" and path == "/.well-known/oauth-authorization-server":
            await _send_json(
                send,
                200,
                {
                    "issuer": base_url,
                    "authorization_endpoint": f"{base_url}/oauth/authorize",
                    "token_endpoint": f"{base_url}/oauth/token",
                    "response_types_supported": ["code"],
                    "grant_types_supported": [
                        "authorization_code",
                        "client_credentials",
                        "refresh_token",
                    ],
                    "token_endpoint_auth_methods_supported": [
                        "client_secret_post",
                        "client_secret_basic",
                    ],
                    "code_challenge_methods_supported": ["S256", "plain"],
                },
            )
            return

        # 3. Authorization Endpoint
        if method == "GET" and path == "/oauth/authorize":
            qs = parse_qs(scope.get("query_string", b"").decode("utf-8"))
            client_id = (qs.get("client_id") or [""])[0]
            redirect_uri = (qs.get("redirect_uri") or [""])[0]
            response_type = (qs.get("response_type") or [""])[0]
            state = (qs.get("state") or [""])[0]
            code_challenge = (qs.get("code_challenge") or [""])[0]
            code_challenge_method = (qs.get("code_challenge_method") or ["plain"])[0]

            if not hmac.compare_digest(client_id, self._creds.client_id):
                await _send_json(send, 400, {"error": "unauthorized_client"})
                return
            if response_type != "code" or not redirect_uri:
                await _send_json(send, 400, {"error": "invalid_request"})
                return

            code = secrets.token_urlsafe(32)
            self._auth_codes[code] = {
                "redirect_uri": redirect_uri,
                "code_challenge": code_challenge,
                "code_challenge_method": code_challenge_method,
                "expires_at": time.time() + 300,
            }

            parsed = urlsplit(redirect_uri)
            existing_params = parse_qs(parsed.query)
            existing_params["code"] = [code]
            if state:
                existing_params["state"] = [state]
            new_query = urlencode(existing_params, doseq=True)
            location = urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment)
            )
            await _send_redirect(send, location)
            return

        # 4. Token Endpoint
        if method == "POST" and path == "/oauth/token":
            raw_body = await _read_body(receive)
            content_type = _get_header(scope, b"content-type").lower()

            if "application/json" in content_type:
                try:
                    form = json.loads(raw_body.decode("utf-8"))
                except json.JSONDecodeError:
                    await _send_json(send, 400, {"error": "invalid_request"})
                    return
            else:
                parsed_form = parse_qs(raw_body.decode("utf-8"))
                form = {k: v[0] for k, v in parsed_form.items() if v}

            client_id = str(form.get("client_id", ""))
            client_secret = str(form.get("client_secret", ""))
            auth_header = _get_header(scope, b"authorization")
            if auth_header.lower().startswith("basic "):
                try:
                    decoded = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
                    basic_id, _, basic_secret = decoded.partition(":")
                    client_id = basic_id
                    client_secret = basic_secret
                except Exception:
                    await _send_json(send, 401, {"error": "invalid_client"})
                    return

            if not (
                hmac.compare_digest(client_id, self._creds.client_id)
                and hmac.compare_digest(client_secret, self._creds.client_secret)
            ):
                await _send_json(send, 401, {"error": "invalid_client"})
                return

            grant_type = str(form.get("grant_type", ""))

            if grant_type == "authorization_code":
                code = str(form.get("code", ""))
                redirect_uri = str(form.get("redirect_uri", ""))
                code_verifier = str(form.get("code_verifier", ""))

                record = self._auth_codes.pop(code, None)
                if not record or record["expires_at"] < time.time():
                    await _send_json(send, 400, {"error": "invalid_grant"})
                    return
                if redirect_uri and redirect_uri != record["redirect_uri"]:
                    await _send_json(send, 400, {"error": "invalid_grant"})
                    return
                if record["code_challenge"]:
                    if not code_verifier or not _verify_pkce(
                        code_verifier,
                        record["code_challenge"],
                        record["code_challenge_method"],
                    ):
                        await _send_json(send, 400, {"error": "invalid_grant"})
                        return

                await _send_json(send, 200, self._issue_tokens())
                return

            if grant_type == "client_credentials":
                await _send_json(send, 200, self._issue_tokens())
                return

            if grant_type == "refresh_token":
                refresh_token = str(form.get("refresh_token", ""))
                if refresh_token not in self._refresh_tokens:
                    await _send_json(send, 400, {"error": "invalid_grant"})
                    return
                self._refresh_tokens.discard(refresh_token)
                await _send_json(send, 200, self._issue_tokens())
                return

            await _send_json(send, 400, {"error": "unsupported_grant_type"})
            return

        # 5. Protect all other routes (including /mcp) with Bearer token
        auth_header = _get_header(scope, b"authorization")
        scheme, _, provided = auth_header.partition(" ")
        is_valid = (
            scheme.lower() == "bearer"
            and bool(provided)
            and self._is_valid_bearer(provided.strip())
        )

        if not is_valid:
            www_auth = (
                f'Bearer realm="mcp", '
                f'resource_metadata="{base_url}/.well-known/oauth-protected-resource"'
            ).encode("latin-1")
            await _send_json(
                send,
                401,
                {"error": "Unauthorized"},
                extra_headers=[(b"www-authenticate", www_auth)],
            )
            return

        await self.app(scope, receive, send)
