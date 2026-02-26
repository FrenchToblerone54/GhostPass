import asyncio
import hashlib
import base64
import json
import logging
from datetime import datetime, timezone
from aiohttp import web
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import ContextTypes, CallbackQueryHandler
import core.db as db
import core.ghostgate as gg
from core.currency import price_for_method, fmt
from bot.strings import t

logger = logging.getLogger(__name__)

_bot_ref = None

def _sign(body_bytes, api_key):
    return hashlib.md5((base64.b64encode(body_bytes).decode()+api_key).encode()).hexdigest()

async def create_invoice(order_id, amount, currency, merchant_id, api_key):
    import httpx
    payload = {"order_id": order_id, "amount": str(amount), "currency": currency}
    body = json.dumps(payload, separators=(",", ":")).encode()
    sign = _sign(body, api_key)
    headers = {"merchant": merchant_id, "sign": sign, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post("https://api.cryptomus.com/v1/payment", content=body, headers=headers)
        r.raise_for_status()
        return r.json()

async def check_invoice(invoice_id, merchant_id, api_key):
    import httpx
    payload = {"uuid": invoice_id}
    body = json.dumps(payload, separators=(",", ":")).encode()
    sign = _sign(body, api_key)
    headers = {"merchant": merchant_id, "sign": sign, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post("https://api.cryptomus.com/v1/payment/info", content=body, headers=headers)
        r.raise_for_status()
        return r.json()

async def cb_buy_crypto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plan_id = query.data.split(":", 2)[2]
    plan = await db.get_plan(plan_id)
    if not plan:
        await query.edit_message_text(t("order_not_found"))
        return
    merchant_id = await db.get_setting("cryptomus_merchant_id", "")
    api_key = await db.get_setting("cryptomus_api_key", "")
    if not merchant_id or not api_key:
        await query.edit_message_text(t("service_unavailable"))
        return
    amount, code, decimals = await price_for_method(plan["price"], "crypto")
    price_str = f"{fmt(amount, decimals)} {code}"
    u = update.effective_user
    uid = await db.upsert_user(u.id, u.username or "", u.first_name or "")
    order_id = await db.create_order(uid, plan_id, "crypto", float(amount), code)
    try:
        result = await create_invoice(order_id, fmt(amount, decimals), code, merchant_id, api_key)
        inv = result.get("result", {})
        invoice_id = inv.get("uuid")
        pay_url = inv.get("url")
    except Exception as e:
        logger.error("Cryptomus invoice error: %s", e)
        await query.edit_message_text(t("ghostgate_error"))
        return
    if not invoice_id or not pay_url:
        await query.edit_message_text(t("ghostgate_error"))
        return
    await db.update_order(order_id, cryptomus_invoice_id=invoice_id)
    text = t("crypto_invoice_created", amount=price_str)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("💳 Open payment page", url=pay_url)]])
    await query.edit_message_text(text, reply_markup=kb)
    asyncio.create_task(_poll_invoice(invoice_id, order_id, u.id, merchant_id, api_key, ctx.bot))

async def _poll_invoice(invoice_id, order_id, telegram_id, merchant_id, api_key, bot):
    for _ in range(120):
        await asyncio.sleep(30)
        try:
            order = await db.get_order(order_id)
            if not order or order["status"]!="pending":
                return
            result = await check_invoice(invoice_id, merchant_id, api_key)
            if result.get("result", {}).get("payment_status") in ("paid", "paid_over"):
                await _activate_order(order_id, telegram_id, bot)
                return
        except Exception as e:
            logger.error("Crypto poll error: %s", e)

async def _activate_order(order_id, telegram_id, bot):
    order = await db.get_order(order_id)
    if not order or order["status"]!="pending":
        return
    plan = await db.get_plan(order["plan_id"])
    user = await db.get_user_by_id(order["user_id"])
    if not plan or not user:
        return
    result = await gg.create_subscription(
        comment=user.get("first_name") or str(user["telegram_id"]),
        data_gb=plan["data_gb"],
        days=plan["days"],
        ip_limit=plan["ip_limit"],
        node_ids=plan["node_ids"]
    )
    if not result:
        return
    sub_id = result.get("id")
    sub_url = result.get("url", "")
    now = datetime.now(timezone.utc).isoformat()
    await db.update_order(order_id, ghostgate_sub_id=sub_id, status="paid", paid_at=now)
    qr_bytes = await gg.get_subscription_qr_bytes(sub_id)
    if qr_bytes:
        import io
        await bot.send_photo(telegram_id, photo=io.BytesIO(qr_bytes), caption=t("crypto_paid", url=sub_url), parse_mode="Markdown")
    else:
        await bot.send_message(telegram_id, t("crypto_paid", url=sub_url), parse_mode="Markdown")

async def _webhook_handler(request):
    try:
        body = await request.read()
        data = json.loads(body)
        merchant_id = await db.get_setting("cryptomus_merchant_id", "")
        api_key = await db.get_setting("cryptomus_api_key", "")
        if not merchant_id or not api_key:
            return web.Response(status=400)
        sign_received = data.get("sign", "")
        data_copy = {k: v for k, v in data.items() if k!="sign"}
        body_check = json.dumps(data_copy, separators=(",", ":"), sort_keys=True).encode()
        if sign_received!=_sign(body_check, api_key):
            logger.warning("Cryptomus webhook signature mismatch")
            return web.Response(status=403)
        status = data.get("payment_status", "")
        order_id = data.get("order_id")
        if status in ("paid", "paid_over") and order_id and _bot_ref:
            order = await db.get_order(order_id)
            if order and order["status"]=="pending":
                user = await db.get_user_by_id(order["user_id"])
                if user:
                    await _activate_order(order_id, user["telegram_id"], _bot_ref)
        return web.Response(text="ok")
    except Exception as e:
        logger.error("Webhook error: %s", e)
        return web.Response(status=500)

async def run_webhook_server(bot=None):
    global _bot_ref
    _bot_ref = bot
    merchant_id = await db.get_setting("cryptomus_merchant_id", "")
    if not merchant_id:
        logger.info("Cryptomus not configured — webhook server not started")
        return
    app = web.Application()
    app.router.add_post("/webhook/cryptomus", _webhook_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8090)
    await site.start()
    logger.info("Cryptomus webhook server started on port 8090")

def get_handlers():
    return [CallbackQueryHandler(cb_buy_crypto, pattern=r"^buy:crypto:")]
