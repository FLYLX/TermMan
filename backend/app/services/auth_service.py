import base64
import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict

logger = logging.getLogger(__name__)


class AuthService:
    """
    鉴权服务 - 按 UPDATE.MD 规范实现

    凭证类型：
    1. 用户Token：JWT格式，由FastAPI security模块处理
    2. 终端临时Token：随机字符串(32位)，短期有效(<10分钟)，一次性使用
    3. Daemon认证Token：随机字符串(64位)，用于Daemon向Backend认证
    4. API_KEY：Daemon唯一标识，预配置

    存储结构：
    - terminal_temp_tokens: {token -> {item_uuid, user_id, expire_at, used}}
    - daemon_auth_tokens: {token -> {api_key, expire_at}}
    """

    DEFAULT_TERMINAL_TOKEN_EXPIRE_MINUTES = 10
    DEFAULT_DAEMON_AUTH_TOKEN_EXPIRE_MINUTES = 30
    DEFAULT_FILE_TICKET_EXPIRE_MINUTES = 5

    def __init__(self):
        self._lock = threading.RLock()

        self.daemon_auth_tokens: dict[str, dict[str, Any]] = {}

        self.api_keys: dict[str, dict[str, Any]] = {}

        self._start_cleanup_thread()

    def _start_cleanup_thread(self):
        def cleanup():
            while True:
                threading.Event().wait(60)
                self._cleanup_expired_tokens()

        thread = threading.Thread(target=cleanup, daemon=True)
        thread.start()

    def _cleanup_expired_tokens(self):
        now = datetime.now()
        with self._lock:
            expired_daemon = [
                token for token, info in self.daemon_auth_tokens.items()
                if now > info.get("expire_at", now)
            ]
            for token in expired_daemon:
                del self.daemon_auth_tokens[token]
                logger.debug("Cleaned up expired daemon auth token")

    @staticmethod
    def generate_terminal_token_hmac(
        item_uuid: str,
        user_id: str,
        api_key: str,
        expire_minutes: int = 5,
    ) -> Dict[str, Any]:
        """Stateless token: daemon verifies locally with its own API_KEY,
        no callback to backend needed."""
        expire_ts = int(time.time()) + expire_minutes * 60
        payload = f"{item_uuid}.{user_id}.{expire_ts}"
        signature = hmac.new(
            api_key.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        return {
            "token": f"{payload}.{signature}",
            "item_uuid": item_uuid,
            "user_id": user_id,
            "expire_at": datetime.fromtimestamp(expire_ts).isoformat(),
            "expires_in": expire_minutes * 60,
        }

    @staticmethod
    def verify_terminal_token_hmac(
        token: str, item_uuid: str, api_key: str
    ) -> Dict[str, Any]:
        parts = token.split(".")
        if len(parts) != 4:
            return {"success": False, "error": "Invalid token format"}
        token_item_uuid, user_id, expire_ts_raw, signature = parts
        if token_item_uuid != item_uuid:
            return {"success": False, "error": "Token item_uuid mismatch"}
        try:
            expire_ts = int(expire_ts_raw)
        except ValueError:
            return {"success": False, "error": "Invalid token expiry"}
        if time.time() > expire_ts:
            return {"success": False, "error": "Token expired"}
        payload = f"{token_item_uuid}.{user_id}.{expire_ts_raw}"
        expected = hmac.new(
            api_key.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return {"success": False, "error": "Invalid token signature"}
        return {"success": True, "user_id": user_id}

    def generate_daemon_auth_token(
        self,
        api_key: str,
        expire_minutes: int = None
    ) -> dict[str, Any]:
        """
        生成Daemon认证Token

        Daemon启动后向Backend认证时使用

        Args:
            api_key: Daemon的API_KEY
            expire_minutes: 过期时间(分钟)，默认30分钟

        Returns:
            包含token和过期时间的字典
        """
        if expire_minutes is None:
            expire_minutes = self.DEFAULT_DAEMON_AUTH_TOKEN_EXPIRE_MINUTES

        token = secrets.token_hex(32)
        expire_at = datetime.now() + timedelta(minutes=expire_minutes)

        with self._lock:
            self.daemon_auth_tokens[token] = {
                "api_key": api_key,
                "expire_at": expire_at,
                "created_at": datetime.now()
            }

        logger.info(f"Generated daemon auth token for api_key=***{api_key[-4:]}, expires_in={expire_minutes}min")

        return {
            "token": token,
            "expire_at": expire_at.isoformat(),
            "expires_in": expire_minutes * 60
        }

    def generate_file_ticket(
        self,
        *,
        item_uuid: str,
        actor_user_id: str,
        owner_user_id: str,
        daemon_api_key: str,
        op: str,
        path: str,
        working_directory: str | None = None,
        allow_overwrite: bool = False,
        expire_minutes: int | None = None,
    ) -> dict[str, Any]:
        """Stateless HMAC ticket: daemon verifies locally, no callback."""
        if expire_minutes is None:
            expire_minutes = self.DEFAULT_FILE_TICKET_EXPIRE_MINUTES

        expire_ts = int(time.time()) + expire_minutes * 60
        payload = {
            "item_uuid": item_uuid,
            "actor_user_id": actor_user_id,
            "owner_user_id": owner_user_id,
            "op": op,
            "path": path,
            "working_directory": working_directory,
            "allow_overwrite": allow_overwrite,
            "expire_ts": expire_ts,
        }
        raw = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode()
        ).decode()
        signature = hmac.new(
            daemon_api_key.encode(), raw.encode(), hashlib.sha256
        ).hexdigest()

        logger.info(
            "Generated file ticket for item=%s, actor=%s, op=%s, expires_in=%smin",
            item_uuid,
            actor_user_id,
            op,
            expire_minutes,
        )

        return {
            "ticket": f"{raw}.{signature}",
            "item_uuid": item_uuid,
            "path": path,
            "op": op,
            "expire_at": datetime.fromtimestamp(expire_ts).isoformat(),
            "expires_in": expire_minutes * 60,
        }

    def validate_file_ticket(
        self,
        *,
        ticket: str,
        op: str,
        daemon_api_key: str,
        mark_used: bool = True,
    ) -> dict[str, Any]:
        try:
            raw, signature = ticket.rsplit(".", 1)
        except ValueError:
            return {"success": False, "error": "Invalid ticket format"}
        expected = hmac.new(
            daemon_api_key.encode(), raw.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return {"success": False, "error": "Invalid ticket signature"}
        try:
            payload = json.loads(base64.urlsafe_b64decode(raw.encode()))
        except Exception:
            return {"success": False, "error": "Invalid ticket payload"}
        if time.time() > float(payload.get("expire_ts") or 0):
            return {"success": False, "error": "Ticket expired"}
        if payload.get("op") != op:
            return {"success": False, "error": "Ticket operation mismatch"}
        return {
            "success": True,
            "item_uuid": payload.get("item_uuid"),
            "actor_user_id": payload.get("actor_user_id"),
            "owner_user_id": payload.get("owner_user_id"),
            "path": payload.get("path"),
            "op": payload.get("op"),
            "working_directory": payload.get("working_directory"),
            "allow_overwrite": payload.get("allow_overwrite"),
        }

    def validate_daemon_auth_token(self, token: str) -> dict[str, Any]:
        """
        验证Daemon认证Token

        Args:
            token: Token字符串

        Returns:
            验证结果 {success, api_key, error}
        """
        with self._lock:
            if token not in self.daemon_auth_tokens:
                return {"success": False, "error": "Token not found"}

            token_info = self.daemon_auth_tokens[token]

            if datetime.now() > token_info["expire_at"]:
                del self.daemon_auth_tokens[token]
                return {"success": False, "error": "Token expired"}

            return {
                "success": True,
                "api_key": token_info["api_key"]
            }

    def consume_daemon_auth_token(self, token: str) -> dict[str, Any]:
        """
        消费Daemon认证Token（主连接建立后调用）

        Args:
            token: Token字符串

        Returns:
            验证结果 {success, api_key, error}
        """
        result = self.validate_daemon_auth_token(token)
        if result["success"]:
            with self._lock:
                if token in self.daemon_auth_tokens:
                    del self.daemon_auth_tokens[token]
                    logger.info(f"Consumed daemon auth token: {token[:8]}...")
        return result

    def generate_access_token(
        self,
        item_uuid: str,
        user_id: str,
        secret_key: str,
        expire_seconds: int = 600
    ) -> str:
        """
        生成浏览器访问Token（用于直连Daemon）

        格式：item_uuid:user_uuid:timestamp:expires_in:signature

        Args:
            item_uuid: 项目UUID
            user_id: 用户ID
            secret_key: 签名密钥
            expire_seconds: 过期时间(秒)，默认10分钟

        Returns:
            签名Token字符串
        """
        timestamp = int(time.time())

        payload = f"{item_uuid}:{user_id}:{timestamp}:{expire_seconds}"

        signature = hmac.new(
            secret_key.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()[:32]

        token = f"{payload}:{signature}"

        logger.info(f"Generated access token for item={item_uuid}, user={user_id}")

        return token

    def verify_access_token(
        self,
        token: str,
        item_uuid: str,
        secret_key: str
    ) -> dict[str, Any]:
        """
        验证浏览器访问Token

        Args:
            token: Token字符串
            item_uuid: 项目UUID
            secret_key: 签名密钥

        Returns:
            验证结果 {success, user_id, error}
        """
        try:
            parts = token.split(":")
            if len(parts) != 5:
                return {"success": False, "error": "Invalid token format"}

            token_item_uuid, user_id, timestamp, expires_in, signature = parts
            timestamp = int(timestamp)
            expires_in = int(expires_in)

            if token_item_uuid != item_uuid:
                return {"success": False, "error": "Token item_uuid mismatch"}

            current_time = int(time.time())
            if current_time > timestamp + expires_in:
                return {"success": False, "error": "Token expired"}

            payload = f"{token_item_uuid}:{user_id}:{timestamp}:{expires_in}"
            expected_signature = hmac.new(
                secret_key.encode(),
                payload.encode(),
                hashlib.sha256
            ).hexdigest()[:32]

            if signature != expected_signature:
                return {"success": False, "error": "Invalid signature"}

            return {
                "success": True,
                "user_id": user_id,
                "item_uuid": item_uuid
            }

        except Exception as e:
            logger.error(f"Error verifying access token: {e}")
            return {"success": False, "error": str(e)}

    def generate_api_key(self, daemon_id: str) -> str:
        """
        生成API Key
        """
        api_key = secrets.token_hex(32)
        with self._lock:
            self.api_keys[api_key] = {
                "daemon_id": daemon_id,
                "created_at": datetime.now(),
                "last_used": None
            }
        return api_key

    def validate_api_key(self, api_key: str) -> str | None:
        """
        验证API Key有效性
        """
        with self._lock:
            if api_key in self.api_keys:
                self.api_keys[api_key]["last_used"] = datetime.now()
                return self.api_keys[api_key]["daemon_id"]
        return None

    def revoke_api_key(self, api_key: str) -> bool:
        """
        撤销API Key
        """
        with self._lock:
            if api_key in self.api_keys:
                del self.api_keys[api_key]
                return True
        return False

    def get_stats(self) -> dict[str, Any]:
        """
        获取认证服务统计信息
        """
        with self._lock:
            return {
                "daemon_auth_tokens": len(self.daemon_auth_tokens),
                "api_keys": len(self.api_keys)
            }


auth_service = AuthService()
