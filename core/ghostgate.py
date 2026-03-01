import asyncio
import logging
import httpx
from config import settings

logger = logging.getLogger(__name__)

def _base():
    return settings.GHOSTGATE_URL

async def _get(path, **kwargs):
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(f"{_base()}/api/{path}", **kwargs)
                if r.status_code==404:
                    return None
                r.raise_for_status()
                return r
        except httpx.RequestError as e:
            if attempt==2:
                logger.error("GhostGate GET %s failed: %s", path, e)
                return None
            await asyncio.sleep(2**attempt)
    return None

async def _post(path, **kwargs):
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(f"{_base()}/api/{path}", **kwargs)
                r.raise_for_status()
                return r
        except httpx.RequestError as e:
            if attempt==2:
                logger.error("GhostGate POST %s failed: %s", path, e)
                return None
            await asyncio.sleep(2**attempt)
    return None

async def _delete(path):
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.delete(f"{_base()}/api/{path}")
                r.raise_for_status()
                return True
        except httpx.RequestError as e:
            if attempt==2:
                logger.error("GhostGate DELETE %s failed: %s", path, e)
                return False
            await asyncio.sleep(2**attempt)
    return False

async def _put(path, **kwargs):
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.put(f"{_base()}/api/{path}", **kwargs)
                r.raise_for_status()
                return True
        except httpx.RequestError as e:
            if attempt==2:
                logger.error("GhostGate PUT %s failed: %s", path, e)
                return False
            await asyncio.sleep(2**attempt)
    return False

async def get_status():
    r = await _get("status")
    return r.json() if r else None

async def list_subscriptions(page=1, per_page=0):
    r = await _get("subscriptions", params={"page": page, "per_page": per_page})
    if not r:
        return []
    data = r.json()
    return data.get("subs", [])

async def get_subscription(sub_id):
    r = await _get(f"subscriptions/{sub_id}")
    return r.json() if r else None

async def create_subscription(comment, data_gb, days, ip_limit, node_ids, expire_after_first_use_seconds=None, note=None):
    body = {"comment": comment, "data_gb": data_gb, "days": days, "ip_limit": ip_limit, "node_ids": node_ids}
    if expire_after_first_use_seconds is not None:
        body["expire_after_first_use_seconds"] = expire_after_first_use_seconds
    if note:
        body["note"] = note
    r = await _post("subscriptions", json=body)
    return r.json() if r else None

async def delete_subscription(sub_id):
    return await _delete(f"subscriptions/{sub_id}")

async def update_subscription(sub_id, **kwargs):
    return await _put(f"subscriptions/{sub_id}", json=kwargs)

async def get_subscription_stats(sub_id):
    r = await _get(f"subscriptions/{sub_id}/stats")
    return r.json() if r else None

async def regen_subscription_id(sub_id):
    r = await _post(f"subscriptions/{sub_id}/regen-id")
    return r.json() if r else None

async def get_subscription_qr_bytes(sub_id):
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(f"{_base()}/api/subscriptions/{sub_id}/qr")
                if r.status_code==404:
                    return None
                r.raise_for_status()
                return r.content
        except httpx.RequestError as e:
            if attempt==2:
                logger.error("GhostGate QR %s failed: %s", sub_id, e)
                return None
            await asyncio.sleep(2**attempt)
    return None

_nodes_cache = None
_nodes_cache_ts = 0.0

async def list_nodes():
    global _nodes_cache, _nodes_cache_ts
    import time
    if _nodes_cache is not None and time.time()-_nodes_cache_ts<300:
        return _nodes_cache
    r = await _get("nodes")
    if not r:
        return _nodes_cache or []
    _nodes_cache = r.json()
    _nodes_cache_ts = time.time()
    return _nodes_cache

def invalidate_nodes_cache():
    global _nodes_cache, _nodes_cache_ts
    _nodes_cache = None
    _nodes_cache_ts = 0.0
