"""Public-client ChatGPT plan authorization; never reads Codex credentials.

Run ``python -m reticle.cognitive.chatgpt_auth login`` before using the provider.
Windows credentials are encrypted with user-scoped DPAPI; Unix files use 0600.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser

from reticle.runtime.ownership import SessionWriterLock

ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
TOKEN_URL = ISSUER + "/api/accounts/oauth/token"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PLAN_SCOPE = "chatgpt.tokens.use.direct"


def credential_dir():
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".config")))
    return root / "reticle" / "chatgpt"


def _dpapi(data, decrypt=False):
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    function = (ctypes.windll.crypt32.CryptUnprotectData if decrypt
                else ctypes.windll.crypt32.CryptProtectData)
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree(target.data)


def _write(path, record):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    raw = json.dumps(record).encode()
    if os.name == "nt":
        raw = _dpapi(raw)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".credentials-")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        if os.name != "nt":
            path.chmod(0o600)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _read(path):
    raw = path.read_bytes()
    return json.loads(_dpapi(raw, decrypt=True) if os.name == "nt" else raw)


def _token_request(form):
    request = urllib.request.Request(TOKEN_URL, urllib.parse.urlencode(form).encode(),
                                    {"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # Do not include response bodies that might contain credentials.
        raise RuntimeError(f"ChatGPT token exchange failed (HTTP {exc.code}); sign in again.") from None


def _validate_identity(tokens, client_id, nonce):
    try:
        import jwt
    except ImportError:
        raise RuntimeError("Install the subscription extra: pip install -e '.[subscription]'") from None
    try:
        key = jwt.PyJWKClient(ISSUER + "/.well-known/jwks.json").get_signing_key_from_jwt(tokens["id_token"])
        claims = jwt.decode(tokens["id_token"], key.key, algorithms=["RS256"],
                            audience=client_id, issuer=ISSUER,
                            options={"require": ["sub", "exp", "iat", "nonce"]}, leeway=5)
    except (jwt.PyJWTError, KeyError):
        raise RuntimeError("ChatGPT identity verification failed; credentials were not saved.") from None
    if not isinstance(claims["nonce"], str) or not secrets.compare_digest(claims["nonce"], nonce):
        raise RuntimeError("ChatGPT ID token nonce mismatch")
    if not isinstance(claims["sub"], str) or not claims["sub"]:
        raise RuntimeError("ChatGPT ID token has no subject")
    return claims


def _updated(record, tokens):
    scopes = tokens.get("scope", " ".join(record.get("scopes", []))).split()
    if PLAN_SCOPE not in scopes:
        raise RuntimeError("ChatGPT plan usage permission was not granted; sign in again.")
    if not tokens.get("access_token") or tokens.get("token_type", "Bearer").lower() != "bearer":
        raise RuntimeError("Token response did not contain a bearer access token")
    return {**record, **{k: tokens[k] for k in ("access_token", "refresh_token", "id_token") if k in tokens},
            "scopes": scopes, "expires_at": time.time() + float(tokens["expires_in"])}


class ChatGPTAuth:
    def __init__(self, root=None):
        self.root = Path(root) if root else credential_dir()
        self.path = self.root / "credentials.dat"

    def access_token(self):
        if not self.path.exists():
            raise RuntimeError("Run python -m reticle.cognitive.chatgpt_auth login first.")
        # Serialize rotating refreshes across pilot processes.
        with SessionWriterLock(self.root).acquire("chatgpt-token-refresh"):
            record = _read(self.path)
            if PLAN_SCOPE not in record.get("scopes", []):
                raise RuntimeError("This registration has no ChatGPT plan permission")
            if record["expires_at"] <= time.time() + 60:
                tokens = _token_request({"grant_type": "refresh_token", "client_id": record["client_id"],
                                         "refresh_token": record["refresh_token"], "resource": RESOURCE})
                record = _updated(record, tokens)
                _write(self.path, record)
            return record["access_token"]

    def login(self, *, new_account=False, timeout=300, open_browser=True):
        # Check the optional dependency before opening an authorization session.
        try:
            import jwt  # noqa: F401
        except ImportError:
            raise RuntimeError("Install the subscription extra: pip install -e '.[subscription]'") from None
        with SessionWriterLock(self.root).acquire("chatgpt-sign-in"):
            host_path = self.root / "host.dat"
            if not host_path.exists():
                _write(host_path, {"id": "urn:uuid:" + str(uuid.uuid4())})
            host_id = _read(host_path)["id"]
            previous = _read(self.path) if self.path.exists() and not new_account else {}
            state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            callback = {}

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass  # authorization codes must never appear in HTTP logs

                def do_GET(self):
                    parsed = urllib.parse.urlparse(self.path)
                    values = urllib.parse.parse_qs(parsed.query)
                    if parsed.path != "/auth/callback" or not secrets.compare_digest(values.get("state", [""])[0], state):
                        self.send_error(400, "Invalid authorization callback")
                        return
                    callback.update({key: value[0] for key, value in values.items()})
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"Authorization received. Return to Reticle to check the result.")

            with HTTPServer(("127.0.0.1", 0), Handler) as server:
                server.timeout = 1
                redirect = f"http://127.0.0.1:{server.server_port}/auth/callback"
                selected_id = previous.get("client_id", "dynamic_agent_client")
                query = {"client_id": selected_id, "ext_agent_host_id": host_id, "response_type": "code",
                         "redirect_uri": redirect, "scope": SCOPES, "resource": RESOURCE,
                         "state": state, "nonce": nonce, "code_challenge_method": "S256", "code_challenge": challenge}
                if previous:
                    if previous.get("id_token"):
                        query["id_token_hint"] = previous["id_token"]
                else:
                    query["agent_name_hint"] = "Reticle Harness"
                url = ISSUER + "/api/accounts/authorize?" + urllib.parse.urlencode(query)
                print("Continue with ChatGPT. Usage counts toward your existing plan limits.", flush=True)
                if open_browser:
                    if not webbrowser.open(url):
                        raise RuntimeError("Browser did not open. Retry login with --no-browser.")
                else:
                    # Never print an authorization URL containing a retained ID token.
                    query.pop("id_token_hint", None)
                    print(ISSUER + "/api/accounts/authorize?" + urllib.parse.urlencode(query), flush=True)
                deadline = time.monotonic() + timeout
                while not callback and time.monotonic() < deadline:
                    server.handle_request()
            if not callback:
                raise RuntimeError("ChatGPT sign-in timed out; retry login.")
            if callback.get("error"):
                raise RuntimeError("ChatGPT sign-in was declined or failed.")
            client_id = callback.get("client_id", previous.get("client_id"))
            if not client_id or client_id == "dynamic_agent_client" or (previous and client_id != selected_id):
                raise RuntimeError("ChatGPT callback returned an invalid client registration")
            tokens = _token_request({"grant_type": "authorization_code", "client_id": client_id,
                                     "code": callback["code"], "code_verifier": verifier,
                                     "redirect_uri": redirect, "resource": RESOURCE})
            identity = _validate_identity(tokens, client_id, nonce)
            if previous and identity["sub"] != previous["subject"]:
                raise RuntimeError("Returning sign-in selected a different account")
            record = _updated({"client_id": client_id, "subject": identity["sub"],
                               "email": identity.get("email"), "ext_agent_host_id": host_id}, tokens)
            if not record.get("refresh_token"):
                raise RuntimeError("ChatGPT did not return a renewable session")
            # Preserve every account registration separately; credentials.dat selects the active one.
            account_key = hashlib.sha256((client_id + identity["sub"]).encode()).hexdigest()
            _write(self.root / "accounts" / (account_key + ".dat"), record)
            _write(self.path, record)
            print("ChatGPT plan connected to Reticle Harness.", flush=True)

    def models(self):
        request = urllib.request.Request(RESOURCE + "/models", headers={"Authorization": "Bearer " + self.access_token()})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)["models"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["login", "models", "smoke"])
    parser.add_argument("--new-account", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--model")
    args = parser.parse_args()
    auth = ChatGPTAuth()
    try:
        if args.command == "login":
            auth.login(new_account=args.new_account, open_browser=not args.no_browser)
        elif args.command == "models":
            print(json.dumps([{k: m[k] for k in ("slug", "display_name") if k in m}
                              for m in auth.models() if m.get("visibility") == "list"], indent=2))
        else:
            if not args.model:
                parser.error("smoke requires --model from the models command")
            from reticle.cognitive.chatgpt_subscription import ChatGPTSubscriptionClient
            client = ChatGPTSubscriptionClient(args.model, auth=auth)
            tool = {"type": "function", "function": {"name": "ping", "description": "Return a test value",
                    "parameters": {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]}}}
            messages = [{"role": "user", "content": "Call ping with value subscription-ok; after its result, reply subscription-ok."}]
            first = client.complete(messages, [tool])
            calls = first.message.get("tool_calls", [])
            if len(calls) != 1 or calls[0]["function"]["name"] != "ping":
                raise RuntimeError("Smoke failed: expected one ping tool call")
            messages += [first.message, {"role": "tool", "tool_call_id": calls[0]["id"], "content": "subscription-ok"}]
            second = client.complete(messages, [tool])
            if "subscription-ok" not in (second.message.get("content") or ""):
                raise RuntimeError("Smoke failed: tool result was not acknowledged")
            print("Subscription smoke passed: tool call and follow-up response.")
    except (RuntimeError, urllib.error.URLError) as exc:
        # Network exception messages do not include request headers.
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
