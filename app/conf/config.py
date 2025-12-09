# pkg/config/config.py

from dataclasses import dataclass, field
from typing import List, Optional
from pkg.smtp_client.client import EmailConfig



@dataclass
class JWTAuthConfig:
    super_secret_key: str
    refresh_secret_key: str



@dataclass
class RedisConfig:
    host: str
    port: str
    password: str


@dataclass
class PostgresConfig:
    host: str
    port: int
    database: str
    user: str
    password: str
    pool_size: int = 5          # default pool size
    max_overflow: int = 10      # default overflow connections
    pool_timeout: int = 30      # seconds
    pool_recycle: int = 86400    # seconds (24 hrs)





@dataclass
class AppConfig:

    jwt_auth: JWTAuthConfig

    redis: RedisConfig
   
    postgres: PostgresConfig
    
    smtp: EmailConfig


