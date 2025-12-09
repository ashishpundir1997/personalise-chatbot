import os
from zep_cloud import Zep


def get_zep_client() -> Zep:
    """Get or create Zep client instance"""
    api_key = os.getenv("ZEP_API_KEY")
    if not api_key:
        raise ValueError("ZEP_API_KEY environment variable is not set")
    return Zep(api_key=api_key)



