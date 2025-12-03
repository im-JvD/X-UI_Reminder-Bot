"""
Panel API client - async version using aiohttp.
"""
import aiohttp
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class PanelAPI:
    """Async API client for X-UI panel"""

    def __init__(
        self,
        username: str,
        password: str,
        base_url: str = "",
        web_base_path: str = ""
    ):
        self.username = username
        self.password = password
        self.base_url = base_url.rstrip("/")
        
        if web_base_path and not web_base_path.startswith('/'):
            web_base_path = '/' + web_base_path
        self.web_base_path = web_base_path.rstrip("/")

        self.session: Optional[aiohttp.ClientSession] = None
        self.cookies: Dict[str, str] = {}
        
        if self.base_url:
            self.login_url = f"{self.base_url}{self.web_base_path}/login"
            self.inbounds_url = f"{self.base_url}{self.web_base_path}/panel/api/inbounds/list"
            self.online_url = f"{self.base_url}{self.web_base_path}/panel/api/inbounds/onlines"
        else:
            self.login_url = ""
            self.inbounds_url = ""
            self.online_url = ""

        logger.debug(f"  Login URL: {self.login_url}")
        logger.debug(f"  Inbounds URL: {self.inbounds_url}")
        logger.debug(f"  Online URL: {self.online_url}")

    async def __aenter__(self):
        """Context manager entry"""
        self.session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=False)
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        if self.session:
            await self.session.close()

    async def _ensure_session(self):
        """Ensure session exists"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=False)
            )

    async def login(self) -> bool:
        """Login to panel and store session"""
        if not self.login_url:
            logger.error("Login URL not configured")
            return False

        await self._ensure_session()

        payload = {
            "username": self.username,
            "password": self.password
        }

        try:
            async with self.session.post(
                self.login_url,
                json=payload,
                ssl=False,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("success"):
                        
                        self.cookies = {
                            cookie.key: cookie.value
                            for cookie in response.cookies.values()
                        }
                        logger.debug(f"Cookies: {list(self.cookies.keys())}")
                        return True
                    else:
                        logger.error(f"Login failed: {data.get('msg', 'Unknown error')}")
                        return False
                else:
                    logger.error(f"Login request failed with status {response.status}")
                    text = await response.text()
                    logger.error(f"Response: {text[:200]}")
                    return False

        except Exception as e:
            logger.error(f"Login exception: {e}")
            return False

    async def inbounds(self) -> List[Dict]:
        """Get list of inbounds using GET method"""
        if not self.inbounds_url:
            logger.error("Inbounds URL not configured")
            return []

        await self._ensure_session()

        try:
            async with self.session.get(
                self.inbounds_url,
                cookies=self.cookies,
                ssl=False,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                logger.debug(f"Inbounds request: {self.inbounds_url} -> {response.status}")

                if response.status == 200:
                    data = await response.json()
                    if data.get("success") and isinstance(data.get("obj"), list):
                        inbounds_count = len(data["obj"])
                        return data["obj"]
                    else:
                        logger.warning(f"Inbounds response not successful: {data.get('msg', 'Unknown')}")
                        return []
                else:
                    logger.error(f"Inbounds request failed with status {response.status}")
                    text = await response.text()
                    logger.error(f"Response: {text[:200]}")
                    return []

        except Exception as e:
            logger.error(f"Inbounds exception: {e}")
            return []

    async def online_clients(self) -> List[str]:
        """Get list of online client emails using POST method"""
        if not self.online_url:
            logger.error("Online URL not configured")
            return []

        await self._ensure_session()

        try:
            async with self.session.post(
                self.online_url,
                cookies=self.cookies,
                ssl=False,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                logger.debug(f"Online clients request: {self.online_url} -> {response.status}")

                if response.status == 200:
                    data = await response.json()
                    if data.get("success"):
                        obj = data.get("obj")
                        if isinstance(obj, list):
                            return obj
                        elif isinstance(obj, str):
                            
                            clients = [x.strip() for x in obj.split(",") if x.strip()]
                            logger.info(f"✅ Retrieved {len(clients)} online clients (string format)")
                            return clients
                    logger.warning("Online clients response not successful")
                    return []
                else:
                    logger.error(f"Online clients request failed with status {response.status}")
                    return []

        except Exception as e:
            logger.error(f"Online clients exception: {e}")
            return []

    async def close(self):
        """Close the session"""
        if self.session and not self.session.closed:
            await self.session.close()