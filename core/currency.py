import json
from decimal import Decimal, ROUND_HALF_UP

async def get_currencies():
    from core.db import get_setting
    raw = await get_setting("currencies_config", None)
    return json.loads(raw) if raw else []

async def save_currencies(currencies):
    from core.db import set_setting
    await set_setting("currencies_config", json.dumps(currencies))

async def get_base_currency():
    from core.db import get_setting
    return await get_setting("base_currency") or await get_setting("currency", "IRT")

async def set_base_currency(code):
    from core.db import set_setting
    await set_setting("base_currency", code)

async def currency_for_method(method):
    for c in await get_currencies():
        if method in c.get("methods", []):
            return c
    return None

def _quantize(amount, decimals):
    if decimals==0:
        return amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return amount.quantize(Decimal(10)**-decimals, rounding=ROUND_HALF_UP)

def convert(plan_price, rate, decimals):
    return _quantize(Decimal(str(plan_price))*Decimal(str(rate)), decimals)

def fmt(amount, decimals):
    if decimals==0:
        return str(int(amount))
    s = f"{amount:.{decimals}f}".rstrip("0").rstrip(".")
    return s

async def price_for_method(plan_price, method):
    c = await currency_for_method(method)
    if not c:
        base = await get_base_currency()
        return Decimal(str(plan_price)), base, 0
    amount = convert(plan_price, c["rate"], c.get("decimals", 2))
    return amount, c["code"], c.get("decimals", 2)

async def fmt_price_for_method(plan_price, method):
    amount, code, decimals = await price_for_method(plan_price, method)
    return f"{fmt(amount, decimals)} {code}"
