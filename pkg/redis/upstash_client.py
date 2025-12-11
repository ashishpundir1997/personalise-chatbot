import httpx
from typing import Optional, Any, Dict, List, Union
import json
import logging
from datetime import timedelta


class UpstashRedisClient:
    """Upstash Redis REST API client"""
    
    def __init__(self, logger: logging.Logger, url: str, token: str):
        self.logger = logger
        self.url = url.rstrip('/')
        self.token = token
        self.client = httpx.Client(
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            timeout=10.0
        )
        # Async client
        self.async_client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            timeout=10.0
        )
        self.logger.info(f"Upstash Redis client initialized for {url}")
    
    def _execute(self, command: list) -> Any:
        """Execute a Redis command via REST API"""
        try:
            response = self.client.post(
                self.url,
                json=command
            )
            response.raise_for_status()
            data = response.json()
            return data.get("result")
        except Exception as e:
            self.logger.error(f"Redis command {command[0]} failed: {e}")
            raise
    
    def ping(self) -> bool:
        """Test connection"""
        result = self._execute(["PING"])
        return result == "PONG"
    
    def get(self, key: str) -> Optional[str]:
        """Get value by key"""
        return self._execute(["GET", key])
    
    def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        """Set key-value pair with optional expiration"""
        if ex:
            result = self._execute(["SET", key, value, "EX", str(ex)])
        else:
            result = self._execute(["SET", key, value])
        return result == "OK"
    
    def delete(self, key: str) -> int:
        """Delete key"""
        return self._execute(["DEL", key])
    
    def exists(self, key: str) -> bool:
        """Check if key exists"""
        return self._execute(["EXISTS", key]) == 1
    
    def setex(self, key: str, seconds: int, value: str) -> bool:
        """Set key with expiration"""
        result = self._execute(["SETEX", key, str(seconds), value])
        return result == "OK"
    
    def ttl(self, key: str) -> int:
        """Get time to live for key"""
        return self._execute(["TTL", key])
    
    def hset(self, name: str, key: str, value: str) -> int:
        """Set hash field"""
        return self._execute(["HSET", name, key, value])
    
    def hget(self, name: str, key: str) -> Optional[str]:
        """Get hash field value"""
        return self._execute(["HGET", name, key])
    
    def hgetall(self, name: str) -> Dict[str, str]:
        """Get all hash fields and values"""
        result = self._execute(["HGETALL", name])
        if result:
            # Convert flat list to dict
            return dict(zip(result[::2], result[1::2]))
        return {}
    
    def hdel(self, name: str, *keys: str) -> int:
        """Delete hash fields"""
        return self._execute(["HDEL", name, *keys])
    
    def expire(self, key: str, seconds: int) -> bool:
        """Set key expiration"""
        return self._execute(["EXPIRE", key, str(seconds)]) == 1
    
    def incr(self, key: str) -> int:
        """Increment key value"""
        return self._execute(["INCR", key])
    
    def decr(self, key: str) -> int:
        """Decrement key value"""
        return self._execute(["DECR", key])
    
    def lpush(self, key: str, *values: str) -> int:
        """Push values to list from left"""
        return self._execute(["LPUSH", key, *values])
    
    def rpush(self, key: str, *values: str) -> int:
        """Push values to list from right"""
        return self._execute(["RPUSH", key, *values])
    
    def lrange(self, key: str, start: int, end: int) -> List[str]:
        """Get list range"""
        result = self._execute(["LRANGE", key, str(start), str(end)])
        return result if result else []
    
    def llen(self, key: str) -> int:
        """Get list length"""
        return self._execute(["LLEN", key]) or 0
    
    def sadd(self, key: str, *members: str) -> int:
        """Add members to set"""
        return self._execute(["SADD", key, *members])
    
    def smembers(self, key: str) -> List[str]:
        """Get all set members"""
        result = self._execute(["SMEMBERS", key])
        return result if result else []
    
    def srem(self, key: str, *members: str) -> int:
        """Remove members from set"""
        return self._execute(["SREM", key, *members])
    
    def keys(self, pattern: str = "*") -> List[str]:
        """Get keys matching pattern"""
        result = self._execute(["KEYS", pattern])
        return result if result else []
    
    def flushdb(self) -> bool:
        """Clear current database"""
        result = self._execute(["FLUSHDB"])
        return result == "OK"
    
    def close(self):
        """Close the HTTP client"""
        self.client.close()
        self.logger.info("Upstash Redis client closed.")
    
    # Compatibility methods for existing codebase
    def get_value(self, key: str, default: Any = None, bypass_cache: bool = False) -> Any:
        """
        Get value for a key (compatibility method)
        
        Args:
            key: Key to retrieve
            default: Default value if key doesn't exist
            bypass_cache: Ignored for REST API (for compatibility)
            
        Returns:
            The value if found, deserialized from JSON if possible,
            otherwise the default value
        """
        try:
            value = self.get(key)
            if value is None:
                return default
            
            # Try to deserialize JSON
            if isinstance(value, str):
                try:
                    if value.startswith('{') or value.startswith('['):
                        return json.loads(value)
                except json.JSONDecodeError:
                    pass
            return value
        except Exception as e:
            self.logger.error(f"Error getting key {key}: {e}")
            return default
    
    def set_value(self, key: str, value: Any, expiry: Optional[Union[int, timedelta]] = None) -> bool:
        """
        Set a key-value pair, optionally with expiry (compatibility method)
        
        Args:
            key: Key to set
            value: Value to set (will be JSON serialized if not string)
            expiry: Expiry time in seconds or timedelta
        """
        try:
            # Serialize value if needed
            if not isinstance(value, (str, int, float, bool)):
                value = json.dumps(value)
            
            # Convert timedelta to seconds
            if isinstance(expiry, timedelta):
                expiry = int(expiry.total_seconds())
            
            return self.set(key, str(value), ex=expiry)
        except Exception as e:
            self.logger.error(f"Error setting key {key}: {e}")
            return False
    
    async def async_get_value(self, key: str, default: Any = None) -> Any:
        """
        Async get value for a key (compatibility method)
        
        Args:
            key: Key to retrieve
            default: Default value if key doesn't exist
            
        Returns:
            The value if found, deserialized from JSON if possible,
            otherwise the default value
        """
        try:
            response = await self.async_client.post(
                self.url,
                json=["GET", key]
            )
            response.raise_for_status()
            data = response.json()
            value = data.get("result")
            
            if value is None:
                return default
            
            # Try to deserialize JSON
            if isinstance(value, str):
                try:
                    if value.startswith('{') or value.startswith('['):
                        return json.loads(value)
                except json.JSONDecodeError:
                    pass
            return value
        except Exception as e:
            self.logger.error(f"Error async getting key {key}: {e}")
            return default
    
    async def async_set_value(self, key: str, value: Any, expiry: Optional[Union[int, timedelta]] = None) -> bool:
        """
        Async set a key-value pair, optionally with expiry (compatibility method)
        
        Args:
            key: Key to set
            value: Value to set (will be JSON serialized if not string)
            expiry: Expiry time in seconds or timedelta
        """
        try:
            # Serialize value if needed
            if not isinstance(value, (str, int, float, bool)):
                value = json.dumps(value)
            
            # Convert timedelta to seconds
            if isinstance(expiry, timedelta):
                expiry = int(expiry.total_seconds())
            
            # Build command
            if expiry:
                command = ["SET", key, str(value), "EX", str(expiry)]
            else:
                command = ["SET", key, str(value)]
            
            response = await self.async_client.post(
                self.url,
                json=command
            )
            response.raise_for_status()
            data = response.json()
            return data.get("result") == "OK"
        except Exception as e:
            self.logger.error(f"Error async setting key {key}: {e}")
            return False
    
    async def async_delete(self, *keys: str) -> int:
        """
        Async delete one or more keys (compatibility method)
        
        Args:
            *keys: One or more keys to delete
            
        Returns:
            Number of keys deleted
        """
        try:
            if not keys:
                return 0
            
            response = await self.async_client.post(
                self.url,
                json=["DEL", *keys]
            )
            response.raise_for_status()
            data = response.json()
            return data.get("result", 0)
        except Exception as e:
            self.logger.error(f"Error async deleting keys {keys}: {e}")
            return 0
