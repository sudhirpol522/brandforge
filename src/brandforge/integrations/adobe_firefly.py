from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, cast

from ..exceptions import ValidationError
from ..model_gateway import DeterministicModelProvider, ModelProvider
from ..security import redact_secrets


class AdobeFireflyProvider(ModelProvider):
    """Server-side Firefly image adapter with a deterministic text fallback."""

    name = "adobe-firefly"
    model_name = "firefly-generate-image-v3"
    text_cost_usd = 0.0001
    image_cost_usd = 0.05

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        base_url: str = "https://firefly-api.adobe.io",
        token_url: str = "https://ims-na1.adobelogin.com/ims/token/v3",
        timeout_seconds: int = 90,
    ) -> None:
        for endpoint in (base_url, token_url):
            parsed = urllib.parse.urlparse(endpoint)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValidationError("Adobe endpoints must be absolute HTTPS URLs")
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url.rstrip("/")
        self.token_url = token_url
        self.timeout_seconds = timeout_seconds
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._lock = threading.Lock()
        self._text_provider = DeterministicModelProvider()

    @classmethod
    def from_env(cls) -> AdobeFireflyProvider:
        client_id = os.getenv("ADOBE_FIREFLY_CLIENT_ID", "")
        client_secret = os.getenv("ADOBE_FIREFLY_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            raise ValidationError("Adobe Firefly credentials are not configured")
        return cls(
            client_id,
            client_secret,
            base_url=os.getenv("ADOBE_FIREFLY_BASE_URL", "https://firefly-api.adobe.io"),
            token_url=os.getenv(
                "ADOBE_IMS_TOKEN_URL", "https://ims-na1.adobelogin.com/ims/token/v3"
            ),
        )

    def generate_text(self, *, purpose: str, prompt: str, seed: int) -> str:
        return self._text_provider.generate_text(purpose=purpose, prompt=prompt, seed=seed)

    def generate_image(self, *, prompt: str, width: int, height: int, seed: int) -> dict[str, Any]:
        payload = {
            "prompt": prompt,
            "size": {"width": width, "height": height},
            "seeds": [seed],
            "numVariations": 1,
        }
        result = self._json_request(
            f"{self.base_url}/v3/images/generate",
            payload,
            {
                "Authorization": f"Bearer {self._access_token()}",
                "x-api-key": self.client_id,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        outputs = result.get("outputs", [])
        output = outputs[0] if outputs and isinstance(outputs[0], dict) else {}
        image = output.get("image", {}) if isinstance(output, dict) else {}
        return {
            "status": "generated",
            "asset_id": output.get("seed", seed),
            "asset_url": image.get("url") if isinstance(image, dict) else None,
            "raw_status": result.get("status"),
        }

    def _access_token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._token_expires_at - 120:
                return self._token
            body = urllib.parse.urlencode(
                {
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": (
                        "openid,AdobeID,session,additional_info,read_organizations,"
                        "firefly_api,ff_apis"
                    ),
                }
            ).encode()
            request = urllib.request.Request(
                self.token_url,
                data=body,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    result = json.loads(response.read())
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                raise ValidationError(
                    redact_secrets(f"Adobe authentication failed: {error}")
                ) from error
            self._token = str(result["access_token"])
            self._token_expires_at = time.time() + int(result.get("expires_in", 3600))
            return self._token

    def _json_request(
        self, url: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode(), method="POST", headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return cast(dict[str, Any], json.loads(response.read()))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise ValidationError(
                redact_secrets(f"Adobe Firefly request failed: {error}")
            ) from error
