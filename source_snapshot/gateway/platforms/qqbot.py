"""
QQ Bot platform adapter using WebSocket Gateway API.

Connects directly to QQ Bot's WebSocket Gateway for receiving and sending messages.
Supports C2C (私聊) and Group @ messages.

Requires:
    pip install websockets httpx
    QQBOT_APP_ID and QQBOT_SECRET env vars

Configuration in config.yaml:
    platforms:
      qqbot:
        enabled: true
        extra:
          app_id: "YOUR_APP_ID"
          secret: "YOUR_CLIENT_SECRET"
"""

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

try:
    import websockets
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    websockets = None

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    httpx = None

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import (
    BasePlatformAdapter,
    MessageEvent,
    MessageType,
    SendResult,
)

logger = logging.getLogger(__name__)

# QQ Bot API endpoints
QQBOT_TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
QQBOT_GATEWAY_URL = "https://api.sgroup.qq.com/gateway"
QQBOT_API_BASE = "https://api.sgroup.qq.com"

# Message intents (bitmask)
INTENT_GUILDS = 1
INTENT_C2C_MESSAGE = 1 << 25  # 33554432
INTENT_GROUP_AT_MESSAGE = 1 << 30  # 1073741824
INTENT_INTERACTION = 1 << 26  # 67108864

# WebSocket opcodes
OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_RESUME = 6
OP_RECONNECT = 7
OP_INVALID_SESSION = 9
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11

# Reconnection backoff (seconds)
RECONNECT_BACKOFF = [2, 5, 10, 30, 60]

# Token refresh threshold (5 minutes before expiry)
TOKEN_REFRESH_THRESHOLD = 300


def check_qqbot_requirements() -> bool:
    """Check if QQ Bot dependencies are available and configured."""
    if not WEBSOCKETS_AVAILABLE:
        logger.warning("[QQBot] websockets not installed. Run: pip install websockets")
        return False
    if not HTTPX_AVAILABLE:
        logger.warning("[QQBot] httpx not installed. Run: pip install httpx")
        return False
    if not os.getenv("QQBOT_APP_ID") or not os.getenv("QQBOT_SECRET"):
        logger.warning("[QQBot] QQBOT_APP_ID and QQBOT_SECRET required")
        return False
    return True


class QQBotAdapter(BasePlatformAdapter):
    """QQ Bot adapter using WebSocket Gateway API.

    Maintains a persistent WebSocket connection to QQ Bot's Gateway.
    Handles authentication, heartbeat, message reception, and reply routing.
    """

    MAX_MESSAGE_LENGTH = 20000

    def __init__(self, config: PlatformConfig):
        super().__init__(config, Platform.QQBOT)

        extra = config.extra or {}
        self._app_id: str = extra.get("app_id") or os.getenv("QQBOT_APP_ID", "")
        self._client_secret: str = extra.get("secret") or extra.get("client_secret") or os.getenv("QQBOT_SECRET", "")

        # Connection state
        self._ws: Any = None
        self._ws_task: Optional[asyncio.Task] = None
        self._http_client: Optional["httpx.AsyncClient"] = None

        # Auth state
        self._access_token: str = ""
        self._token_expires_at: float = 0
        self._session_id: str = ""
        self._last_seq: int = 0
        self._heartbeat_interval: float = 45.0
        self._heartbeat_task: Optional[asyncio.Task] = None

        # Message deduplication
        self._seen_messages: Dict[str, float] = {}
        self._dedup_window = 300
        self._dedup_max_size = 1000

        # Message sequence tracking (per chat)
        self._msg_seq: Dict[str, int] = {}

    # -- Token management ---------------------------------------------------

    async def _refresh_token(self) -> bool:
        """Get or refresh the access token."""
        if not self._http_client:
            self._http_client = httpx.AsyncClient(timeout=30.0)

        try:
            resp = await self._http_client.post(
                QQBOT_TOKEN_URL,
                json={"appId": self._app_id, "clientSecret": self._client_secret},
            )
            resp.raise_for_status()
            data = resp.json()

            self._access_token = data.get("access_token", "")
            expires_in = int(data.get("expires_in", 7200))
            self._token_expires_at = time.time() + expires_in

            logger.info("[QQBot] Token refreshed, expires in %ds", expires_in)
            return True
        except Exception as e:
            logger.error("[QQBot] Failed to refresh token: %s", e)
            return False

    def _token_needs_refresh(self) -> bool:
        """Check if token needs refresh (within threshold of expiry)."""
        if not self._access_token:
            return True
        return time.time() > (self._token_expires_at - TOKEN_REFRESH_THRESHOLD)

    def _get_auth_header(self) -> str:
        """Get the Authorization header value."""
        return f"QQBot {self._access_token}"

    # -- Gateway URL --------------------------------------------------------

    async def _get_gateway_url(self) -> str:
        """Get the WebSocket gateway URL."""
        try:
            resp = await self._http_client.get(
                QQBOT_GATEWAY_URL,
                headers={"Authorization": self._get_auth_header()},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("url", "")
        except Exception as e:
            logger.error("[QQBot] Failed to get gateway URL: %s", e)
            return ""

    # -- Connection lifecycle -----------------------------------------------

    async def connect(self) -> bool:
        """Connect to QQ Bot Gateway."""
        if not check_qqbot_requirements():
            return False

        try:
            # Refresh token
            if not await self._refresh_token():
                return False

            # Get gateway URL
            gateway_url = await self._get_gateway_url()
            if not gateway_url:
                return False

            # Create HTTP client for API calls
            if not self._http_client:
                self._http_client = httpx.AsyncClient(timeout=30.0)

            # Start WebSocket connection
            self._ws_task = asyncio.create_task(self._run_websocket(gateway_url))
            self._mark_connected()
            logger.info("[QQBot] Connected to Gateway")
            return True

        except Exception as e:
            logger.error("[QQBot] Failed to connect: %s", e)
            return False

    async def _run_websocket(self, gateway_url: str) -> None:
        """Main WebSocket loop with auto-reconnection."""
        backoff_idx = 0
        url = gateway_url

        while self._running:
            try:
                # Refresh token if needed
                if self._token_needs_refresh():
                    await self._refresh_token()

                # Connect to WebSocket
                logger.debug("[QQBot] Connecting to %s", url[:80])
                async with websockets.connect(url) as ws:
                    self._ws = ws
                    backoff_idx = 0

                    # Start heartbeat task
                    if self._heartbeat_task:
                        self._heartbeat_task.cancel()
                    self._heartbeat_task = asyncio.create_task(self._run_heartbeat())

                    # Process messages
                    await self._process_websocket_messages(ws)

            except asyncio.CancelledError:
                return
            except Exception as e:
                if not self._running:
                    return
                logger.warning("[QQBot] WebSocket error: %s", e)

            if not self._running:
                return

            # Reconnect with backoff
            delay = RECONNECT_BACKOFF[min(backoff_idx, len(RECONNECT_BACKOFF) - 1)]
            logger.info("[QQBot] Reconnecting in %ds...", delay)
            await asyncio.sleep(delay)
            backoff_idx += 1

            # Get fresh gateway URL on reconnect
            if self._token_needs_refresh():
                await self._refresh_token()
            url = await self._get_gateway_url() or url

    async def _process_websocket_messages(self, ws: Any) -> None:
        """Process incoming WebSocket messages."""
        async for raw_message in ws:
            try:
                payload = json.loads(raw_message)
                await self._handle_payload(payload)
            except json.JSONDecodeError:
                logger.warning("[QQBot] Invalid JSON received")
            except Exception as e:
                logger.error("[QQBot] Error processing message: %s", e)

    async def _handle_payload(self, payload: Dict[str, Any]) -> None:
        """Handle a WebSocket payload from the gateway."""
        op = payload.get("op")
        seq = payload.get("s")
        event_type = payload.get("t")
        data = payload.get("d")

        # Update sequence number
        if seq is not None:
            self._last_seq = seq

        if op == OP_HELLO:
            # Server hello - contains heartbeat interval
            self._heartbeat_interval = data.get("heartbeat_interval", 45000) / 1000.0
            logger.info("[QQBot] Hello received, heartbeat interval: %.1fs", self._heartbeat_interval)
            # Send identify
            await self._send_identify()

        elif op == OP_DISPATCH:
            # Event dispatch
            await self._handle_event(event_type, data)

        elif op == OP_HEARTBEAT_ACK:
            logger.debug("[QQBot] Heartbeat ACK received")

        elif op == OP_RECONNECT:
            logger.warning("[QQBot] Server requested reconnect")
            if self._ws:
                await self._ws.close()

        elif op == OP_INVALID_SESSION:
            logger.warning("[QQBot] Invalid session, will re-identify")
            self._session_id = ""
            self._last_seq = 0
            if self._ws:
                await self._ws.close()

    async def _send_identify(self) -> None:
        """Send identify payload to authenticate."""
        intents = INTENT_GUILDS | INTENT_C2C_MESSAGE | INTENT_GROUP_AT_MESSAGE | INTENT_INTERACTION

        identify = {
            "op": OP_IDENTIFY,
            "d": {
                "token": self._get_auth_header(),
                "intents": intents,
                "shard": [0, 1],
                "properties": {},
            }
        }

        if self._ws:
            await self._ws.send(json.dumps(identify))
            logger.info("[QQBot] Identify sent")

    async def _run_heartbeat(self) -> None:
        """Send heartbeats at the configured interval."""
        while self._running:
            await asyncio.sleep(self._heartbeat_interval)
            if self._ws and self._running:
                try:
                    payload = {"op": OP_HEARTBEAT, "d": self._last_seq}
                    await self._ws.send(json.dumps(payload))
                    logger.debug("[QQBot] Heartbeat sent (seq=%d)", self._last_seq)
                except Exception as e:
                    logger.warning("[QQBot] Heartbeat failed: %s", e)

    async def _handle_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Handle an incoming event from the gateway."""
        if event_type == "READY":
            self._session_id = data.get("session_id", "")
            logger.info("[QQBot] READY - session: %s", self._session_id[:20])

        elif event_type == "C2C_MESSAGE_CREATE":
            await self._handle_c2c_message(data)

        elif event_type == "GROUP_AT_MESSAGE_CREATE":
            await self._handle_group_message(data)

        elif event_type == "INTERACTION_CREATE":
            await self._handle_interaction(data)

        else:
            logger.debug("[QQBot] Unhandled event: %s", event_type)

    # -- Message handling ---------------------------------------------------

    async def _handle_c2c_message(self, data: Dict[str, Any]) -> None:
        """Handle a C2C (私聊) message."""
        msg_id = data.get("id", uuid.uuid4().hex)
        if self._is_duplicate(msg_id):
            return

        content = data.get("content", "")
        if not content:
            return

        author = data.get("author", {})
        user_openid = author.get("user_openid", "")

        chat_id = f"c2c:{user_openid}"
        timestamp = self._parse_timestamp(data.get("timestamp"))

        source = self.build_source(
            chat_id=chat_id,
            chat_type="dm",
            user_id=user_openid,
            user_name=user_openid[:12],
        )

        event = MessageEvent(
            text=content,
            message_type=MessageType.TEXT,
            source=source,
            message_id=msg_id,
            raw_message=data,
            timestamp=timestamp,
        )

        logger.debug("[QQBot] C2C msg from %s: %s", user_openid[:12], content[:50])
        await self.handle_message(event)

    async def _handle_group_message(self, data: Dict[str, Any]) -> None:
        """Handle a Group @ message."""
        msg_id = data.get("id", uuid.uuid4().hex)
        if self._is_duplicate(msg_id):
            return

        content = data.get("content", "")
        if not content:
            return

        author = data.get("author", {})
        user_openid = author.get("user_openid", "")
        group_openid = data.get("group_openid", "")

        chat_id = f"group:{group_openid}"
        timestamp = self._parse_timestamp(data.get("timestamp"))

        source = self.build_source(
            chat_id=chat_id,
            chat_name=group_openid[:16],
            chat_type="group",
            user_id=user_openid,
            user_name=user_openid[:12],
        )

        event = MessageEvent(
            text=content,
            message_type=MessageType.TEXT,
            source=source,
            message_id=msg_id,
            raw_message=data,
            timestamp=timestamp,
        )

        logger.debug("[QQBot] Group msg from %s in %s: %s", user_openid[:12], group_openid[:12], content[:50])
        await self.handle_message(event)

    async def _handle_interaction(self, data: Dict[str, Any]) -> None:
        """Handle an interaction event (acknowledge within 5s)."""
        interaction_id = data.get("id", "")
        if not interaction_id:
            return

        try:
            await self._acknowledge_interaction(interaction_id)
        except Exception as e:
            logger.warning("[QQBot] Failed to acknowledge interaction: %s", e)

    async def _acknowledge_interaction(self, interaction_id: str) -> None:
        """Acknowledge an interaction to prevent timeout."""
        if not self._http_client:
            return

        url = f"{QQBOT_API_BASE}/interactions/{interaction_id}"
        await self._http_client.put(
            url,
            json={"code": 0},
            headers={"Authorization": self._get_auth_header()},
        )

    @staticmethod
    def _parse_timestamp(ts_str: Optional[str]) -> datetime:
        """Parse QQ Bot timestamp to datetime."""
        if not ts_str:
            return datetime.now(tz=timezone.utc)
        try:
            return datetime.fromisoformat(ts_str)
        except (ValueError, TypeError):
            return datetime.now(tz=timezone.utc)

    # -- Deduplication ------------------------------------------------------

    def _is_duplicate(self, msg_id: str) -> bool:
        """Check and record a message ID. Returns True if already seen."""
        now = time.time()
        if len(self._seen_messages) > self._dedup_max_size:
            cutoff = now - self._dedup_window
            self._seen_messages = {k: v for k, v in self._seen_messages.items() if v > cutoff}

        if msg_id in self._seen_messages:
            return True
        self._seen_messages[msg_id] = now
        return False

    # -- Outbound messaging -------------------------------------------------

    def _get_msg_seq(self, chat_id: str) -> int:
        """Get and increment message sequence for a chat."""
        seq = self._msg_seq.get(chat_id, 0) + 1
        self._msg_seq[chat_id] = seq
        return seq

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        """Send a message to a QQ Bot chat."""
        metadata = metadata or {}

        if not self._http_client:
            return SendResult(success=False, error="HTTP client not initialized")

        # Refresh token if needed
        if self._token_needs_refresh():
            await self._refresh_token()

        # Determine endpoint based on chat type
        if chat_id.startswith("c2c:"):
            openid = chat_id[4:]
            url = f"{QQBOT_API_BASE}/v2/users/{openid}/messages"
            chat_type = "C2C"
        elif chat_id.startswith("group:"):
            group_openid = chat_id[6:]
            url = f"{QQBOT_API_BASE}/v2/groups/{group_openid}/messages"
            chat_type = "GROUP"
        else:
            return SendResult(success=False, error=f"Invalid chat_id format: {chat_id}")

        msg_seq = self._get_msg_seq(chat_id)
        msg_id = metadata.get("msg_id", reply_to)

        payload = {
            "content": content,
            "msg_type": 0,  # 0 = text
            "msg_seq": msg_seq,
        }

        if msg_id:
            payload["msg_id"] = msg_id

        try:
            resp = await self._http_client.post(
                url,
                json=payload,
                headers={"Authorization": self._get_auth_header()},
            )
            resp.raise_for_status()
            data = resp.json()
            result_msg_id = data.get("id", "")
            logger.info("[QQBot] Message sent to %s, msg_id=%s", chat_id[:20], result_msg_id)
            return SendResult(success=True, message_id=result_msg_id)
        except Exception as e:
            logger.error("[QQBot] Failed to send message: %s", e)
            return SendResult(success=False, error=str(e))

    # -- Connection teardown ------------------------------------------------

    async def disconnect(self) -> None:
        """Disconnect from QQ Bot Gateway."""
        self._running = False

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

        if self._ws_task:
            self._ws_task.cancel()
            self._ws_task = None

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass

        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

        self._mark_disconnected()
        logger.info("[QQBot] Disconnected")

    # -- Formatting helpers -------------------------------------------------

    def format_user_mention(self, user_id: str, display_name: str = "") -> str:
        """Format a user mention for QQ Bot."""
        return f"<@{user_id}>"

    def format_message_chunks(self, content: str) -> list[str]:
        """Split content into chunks respecting max message length."""
        if len(content) <= self.MAX_MESSAGE_LENGTH:
            return [content]

        chunks = []
        while content:
            if len(content) <= self.MAX_MESSAGE_LENGTH:
                chunks.append(content)
                break

            # Find a safe split point
            split_at = content.rfind("\n", 0, self.MAX_MESSAGE_LENGTH)
            if split_at == -1:
                split_at = self.MAX_MESSAGE_LENGTH

            chunks.append(content[:split_at])
            content = content[split_at:].lstrip()

        return chunks

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        """Get information about a QQ Bot chat."""
        if chat_id.startswith("c2c:"):
            return {"name": chat_id[4:][:12], "type": "dm", "chat_id": chat_id}
        elif chat_id.startswith("group:"):
            return {"name": chat_id[6:][:16], "type": "group", "chat_id": chat_id}
        return {"name": chat_id, "type": "unknown", "chat_id": chat_id}
