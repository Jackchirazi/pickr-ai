"""
Pickr AI - Email Provider Adapter (SmartLead / Instantly)
Spec: Do NOT build your own email sender. Use SmartLead or Instantly.
This is the provider abstraction layer.

The adapter handles:
  - Campaign creation/selection
  - Lead push to provider
  - Sequence start
  - Reply sending via provider
  - Webhook processing for delivery events and replies
"""
import logging
import httpx
from typing import Optional
from abc import ABC, abstractmethod
from pickr.config import (
    EMAIL_PROVIDER, SMARTLEAD_API_KEY, SMARTLEAD_BASE_URL,
    INSTANTLY_API_KEY, INSTANTLY_BASE_URL,
)

logger = logging.getLogger(__name__)


class ProviderAdapter(ABC):
    """Abstract interface for email provider adapters."""

    @abstractmethod
    async def ensure_campaign(
        self,
        campaign_key: str,
        sender_email: str,
        sender_name: str,
    ) -> dict:
        """Create or find existing campaign. Returns {provider_campaign_id}."""
        ...

    @abstractmethod
    async def push_lead(
        self,
        provider_campaign_id: str,
        email: str,
        lead_id: str,
        sequence_id: str,
        custom_vars: dict,
    ) -> dict:
        """Push lead to provider. Returns {provider_lead_id}."""
        ...

    @abstractmethod
    async def start_sequence(
        self,
        provider_campaign_id: str,
        provider_lead_id: str,
        emails: list[dict],
    ) -> dict:
        """Start email sequence. Returns {status, next_send}."""
        ...

    @abstractmethod
    async def send_reply(
        self,
        provider_campaign_id: str,
        provider_lead_id: str,
        subject: str,
        body: str,
    ) -> dict:
        """Send a manual reply. Returns {provider_message_id}."""
        ...

    @abstractmethod
    async def pause_sequence(
        self,
        provider_campaign_id: str,
        provider_lead_id: str,
    ) -> dict:
        """Pause sequence for a lead."""
        ...

    @abstractmethod
    def parse_webhook(self, payload: dict) -> dict:
        """Parse incoming webhook and return normalized event."""
        ...


class SmartLeadAdapter(ProviderAdapter):
    """SmartLead email provider integration."""

    def __init__(self):
        self.api_key = SMARTLEAD_API_KEY
        self.base_url = SMARTLEAD_BASE_URL
        self.client = httpx.AsyncClient(timeout=30)

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        """Make authenticated request to SmartLead API."""
        url = f"{self.base_url}{path}"
        params = kwargs.pop("params", {})
        params["api_key"] = self.api_key

        try:
            resp = await self.client.request(method, url, params=params, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            logger.error(f"SmartLead API error: {e}")
            return {"error": str(e)}

    async def ensure_campaign(
        self,
        campaign_key: str,
        sender_email: str,
        sender_name: str,
    ) -> dict:
        """Create or get SmartLead campaign."""
        # List existing campaigns to check
        campaigns = await self._request("GET", "/campaigns")
        if isinstance(campaigns, list):
            for camp in campaigns:
                if camp.get("name") == campaign_key:
                    return {"provider_campaign_id": str(camp["id"])}

        # Create new campaign
        result = await self._request("POST", "/campaigns/create", json={
            "name": campaign_key,
        })

        campaign_id = result.get("id")
        if campaign_id:
            # Set sender account
            await self._request(
                "POST",
                f"/campaigns/{campaign_id}/settings",
                json={
                    "from_email": sender_email,
                    "from_name": sender_name,
                },
            )
            return {"provider_campaign_id": str(campaign_id)}

        return {"error": "Failed to create campaign", "detail": result}

    async def push_lead(
        self,
        provider_campaign_id: str,
        email: str,
        lead_id: str,
        sequence_id: str,
        custom_vars: dict,
    ) -> dict:
        """Add lead to SmartLead campaign."""
        lead_data = {
            "email": email,
            "custom_fields": {
                "lead_id": lead_id,
                "sequence_id": sequence_id,
                **custom_vars,
            },
        }

        result = await self._request(
            "POST",
            f"/campaigns/{provider_campaign_id}/leads",
            json={"lead_list": [lead_data]},
        )

        if "error" not in result:
            return {"provider_lead_id": f"sl-{lead_id}"}
        return result

    async def start_sequence(
        self,
        provider_campaign_id: str,
        provider_lead_id: str,
        emails: list[dict],
    ) -> dict:
        """Add sequence steps and start campaign for lead."""
        # Add email steps to campaign
        for i, email in enumerate(emails):
            await self._request(
                "POST",
                f"/campaigns/{provider_campaign_id}/sequences",
                json={
                    "seq_number": i + 1,
                    "subject": email["subject"],
                    "email_body": email["body"],
                    "seq_delay_details": {
                        "delay_in_days": email.get("delay_days", 0),
                    },
                },
            )

        # Start campaign
        result = await self._request(
            "POST",
            f"/campaigns/{provider_campaign_id}/status",
            json={"status": "START"},
        )

        return {"status": "active", "detail": result}

    async def send_reply(
        self,
        provider_campaign_id: str,
        provider_lead_id: str,
        subject: str,
        body: str,
    ) -> dict:
        """Send reply via SmartLead."""
        result = await self._request(
            "POST",
            f"/campaigns/{provider_campaign_id}/reply",
            json={
                "lead_id": provider_lead_id,
                "subject": subject,
                "body": body,
            },
        )
        return {"provider_message_id": result.get("message_id"), "detail": result}

    async def pause_sequence(
        self,
        provider_campaign_id: str,
        provider_lead_id: str,
    ) -> dict:
        """Pause sequence for a lead in SmartLead."""
        result = await self._request(
            "POST",
            f"/campaigns/{provider_campaign_id}/leads/status",
            json={
                "lead_id": provider_lead_id,
                "status": "PAUSED",
            },
        )
        return {"status": "paused", "detail": result}

    def parse_webhook(self, payload: dict) -> dict:
        """Parse SmartLead webhook payload into normalized event."""
        event_type = payload.get("event_type", "")
        lead_email = payload.get("lead_email", "")
        campaign_id = payload.get("campaign_id")

        normalized = {
            "provider": "smartlead",
            "raw": payload,
        }

        if event_type == "EMAIL_SENT":
            normalized["event"] = "sent"
            normalized["email"] = lead_email
            normalized["campaign_id"] = str(campaign_id)
        elif event_type == "EMAIL_OPENED":
            normalized["event"] = "opened"
            normalized["email"] = lead_email
        elif event_type == "EMAIL_REPLIED":
            normalized["event"] = "replied"
            normalized["email"] = lead_email
            normalized["reply_text"] = payload.get("reply_text", "")
        elif event_type == "EMAIL_BOUNCED":
            normalized["event"] = "bounced"
            normalized["email"] = lead_email
        elif event_type == "EMAIL_UNSUBSCRIBED":
            normalized["event"] = "unsubscribed"
            normalized["email"] = lead_email
        else:
            normalized["event"] = "unknown"
            normalized["raw_type"] = event_type

        return normalized


class InstantlyAdapter(ProviderAdapter):
    """Instantly.ai email provider integration."""

    def __init__(self):
        self.api_key = INSTANTLY_API_KEY
        self.base_url = INSTANTLY_BASE_URL
        self.client = httpx.AsyncClient(timeout=30)

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        """Make authenticated request to Instantly API."""
        url = f"{self.base_url}{path}"
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            resp = await self.client.request(method, url, headers=headers, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            logger.error(f"Instantly API error: {e}")
            return {"error": str(e)}

    async def ensure_campaign(
        self,
        campaign_key: str,
        sender_email: str,
        sender_name: str,
    ) -> dict:
        """Create or get Instantly campaign."""
        # List campaigns
        result = await self._request("GET", "/campaign/list")
        campaigns = result if isinstance(result, list) else result.get("data", [])

        for camp in campaigns:
            if camp.get("name") == campaign_key:
                return {"provider_campaign_id": camp["id"]}

        # Create new
        result = await self._request("POST", "/campaign/create", json={
            "name": campaign_key,
            "from_email": sender_email,
            "from_name": sender_name,
        })

        campaign_id = result.get("id") or result.get("campaign_id")
        if campaign_id:
            return {"provider_campaign_id": str(campaign_id)}

        return {"error": "Failed to create campaign", "detail": result}

    async def push_lead(
        self,
        provider_campaign_id: str,
        email: str,
        lead_id: str,
        sequence_id: str,
        custom_vars: dict,
    ) -> dict:
        """Add lead to Instantly campaign."""
        result = await self._request(
            "POST",
            "/lead/add",
            json={
                "campaign_id": provider_campaign_id,
                "email": email,
                "custom_variables": {
                    "lead_id": lead_id,
                    "sequence_id": sequence_id,
                    **custom_vars,
                },
            },
        )
        return {"provider_lead_id": f"inst-{lead_id}"}

    async def start_sequence(
        self,
        provider_campaign_id: str,
        provider_lead_id: str,
        emails: list[dict],
    ) -> dict:
        """Instantly handles sequence via campaign settings."""
        # Add sequence steps
        for i, email in enumerate(emails):
            await self._request(
                "POST",
                f"/campaign/{provider_campaign_id}/sequence/add",
                json={
                    "step": i + 1,
                    "subject": email["subject"],
                    "body": email["body"],
                    "delay": email.get("delay_days", 0),
                },
            )

        # Launch campaign
        await self._request(
            "POST",
            f"/campaign/{provider_campaign_id}/launch",
        )

        return {"status": "active"}

    async def send_reply(
        self,
        provider_campaign_id: str,
        provider_lead_id: str,
        subject: str,
        body: str,
    ) -> dict:
        """Send reply via Instantly."""
        result = await self._request(
            "POST",
            "/unibox/reply",
            json={
                "campaign_id": provider_campaign_id,
                "lead_id": provider_lead_id,
                "subject": subject,
                "body": body,
            },
        )
        return {"provider_message_id": result.get("id"), "detail": result}

    async def pause_sequence(
        self,
        provider_campaign_id: str,
        provider_lead_id: str,
    ) -> dict:
        """Pause lead in Instantly campaign."""
        result = await self._request(
            "POST",
            "/lead/update",
            json={
                "campaign_id": provider_campaign_id,
                "lead_id": provider_lead_id,
                "status": "paused",
            },
        )
        return {"status": "paused", "detail": result}

    def parse_webhook(self, payload: dict) -> dict:
        """Parse Instantly webhook into normalized event."""
        event_type = payload.get("event", "")
        normalized = {
            "provider": "instantly",
            "raw": payload,
        }

        event_map = {
            "email_sent": "sent",
            "email_opened": "opened",
            "reply_received": "replied",
            "email_bounced": "bounced",
            "lead_unsubscribed": "unsubscribed",
        }

        normalized["event"] = event_map.get(event_type, "unknown")
        normalized["email"] = payload.get("lead_email", "")
        if normalized["event"] == "replied":
            normalized["reply_text"] = payload.get("reply_body", "")

        return normalized


def get_provider() -> ProviderAdapter:
    """Factory: return the configured email provider adapter."""
    if EMAIL_PROVIDER == "instantly":
        return InstantlyAdapter()
    return SmartLeadAdapter()  # Default
