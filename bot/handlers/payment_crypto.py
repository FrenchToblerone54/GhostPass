import asyncio
import hashlib
import base64
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from aiohttp import web
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import ContextTypes, CallbackQueryHandler
import core.db as db
import core.ghostgate as gg
from core.currency import price_for_method, fmt, get_enabled_gp_pairs, price_for_gp_pair
from bot.strings import t
from bot.guards import ensure_force_join
from bot.notifications import admin_event
from config import settings

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

async def create_invoice_btcpay(order_id, amount, currency, base_url, store_id, api_key):
    import httpx
    payload={"amount": float(amount), "currency": currency, "metadata": {"orderId": order_id}}
    headers={"Authorization": f"token {api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=20) as c:
        r=await c.post(f"{base_url.rstrip('/')}/api/v1/stores/{store_id}/invoices", json=payload, headers=headers)
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

async def check_invoice_btcpay(invoice_id, base_url, store_id, api_key):
    import httpx
    headers={"Authorization": f"token {api_key}"}
    async with httpx.AsyncClient(timeout=20) as c:
        r=await c.get(f"{base_url.rstrip('/')}/api/v1/stores/{store_id}/invoices/{invoice_id}", headers=headers)
        r.raise_for_status()
        return r.json()

async def create_invoice_ghostpayments(base_url, api_key, chain, token, amount_native, order_id):
    import httpx
    payload={"chain": chain, "token": token, "amount_native": str(amount_native), "metadata": {"order_id": order_id}}
    headers={"X-GhostPay-Key": api_key, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=20) as c:
        r=await c.post(f"{base_url.rstrip('/')}/api/invoice", json=payload, headers=headers)
        r.raise_for_status()
        return r.json()

async def check_invoice_ghostpayments(base_url, invoice_id):
    import httpx
    async with httpx.AsyncClient(timeout=20) as c:
        r=await c.get(f"{base_url.rstrip('/')}/api/invoice/{invoice_id}")
        r.raise_for_status()
        return r.json()

async def cb_buy_crypto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await ensure_force_join(update, ctx):
        return
    plan_id = query.data.split(":", 2)[2]
    plan = await db.get_plan(plan_id)
    if not plan:
        await query.edit_message_text(t("order_not_found"))
        return
    merchant_id = await db.get_setting("cryptomus_merchant_id", "")
    api_key = await db.get_setting("cryptomus_api_key", "")
    btcpay_url = settings.BTCPAY_URL or await db.get_setting("btcpay_url", "")
    btcpay_store = settings.BTCPAY_STORE_ID or await db.get_setting("btcpay_store_id", "")
    btcpay_key = settings.BTCPAY_API_KEY or await db.get_setting("btcpay_api_key", "")
    gp_url = settings.GHOSTPAYMENTS_URL or await db.get_setting("ghostpayments_url", "")
    gp_key = settings.GHOSTPAYMENTS_API_KEY or await db.get_setting("ghostpayments_api_key", "")
    gp_enabled = await db.get_setting("ghostpayments_enabled", "0")=="1"
    use_ghostpayments=bool(gp_enabled and gp_url and gp_key)
    use_btcpay=bool(btcpay_url and btcpay_store and btcpay_key)
    if not use_ghostpayments and not use_btcpay and (not merchant_id or not api_key):
        await query.edit_message_text(t("service_unavailable"))
        return
    if use_ghostpayments:
        enabled_pairs = await get_enabled_gp_pairs()
        if len(enabled_pairs)>1:
            rows = [[InlineKeyboardButton(f"{p['chain']}/{p['token']}", callback_data=f"buy:gp:{plan_id}:{p['chain']}:{p['token']}")] for p in enabled_pairs]
            rows.append([InlineKeyboardButton(t("btn_back"), callback_data=f"plan:{plan_id}")])
            await query.edit_message_text(t("gp_pair_select_title"), reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")
            return
        elif len(enabled_pairs)==1:
            gp_chain, gp_token = enabled_pairs[0]["chain"], enabled_pairs[0]["token"]
        else:
            use_ghostpayments, gp_chain, gp_token = False, "", ""
    else:
        gp_chain, gp_token = "", ""
    discount_pct = ctx.user_data.get(f"discount_pct:{plan_id}", 0)
    discount_max = ctx.user_data.get(f"discount_max:{plan_id}", 0)
    if not discount_pct:
        offer = await db.get_active_offer_for_plan(plan_id)
        if offer:
            discount_pct = offer["discount_percent"]
            discount_max = 0
    if discount_pct:
        discount = Decimal(str(plan["price"])) * Decimal(str(discount_pct)) / 100
        if discount_max > 0:
            discount = min(discount, Decimal(str(discount_max)))
        effective_price = float(Decimal(str(plan["price"])) - discount)
    else:
        effective_price = plan["price"]
    u = update.effective_user
    uid = await db.upsert_user(u.id, u.username or "", u.first_name or "")
    wallet_use = ctx.user_data.pop(f"wallet_use:{plan_id}", False)
    wallet_deduct = 0.0
    if wallet_use:
        wallet_balance = await db.get_wallet_balance(uid)
        wallet_deduct = min(wallet_balance, effective_price)
        effective_price = max(0.0, effective_price-wallet_deduct)
    discount_code_used = ctx.user_data.pop(f"discount_code:{plan_id}", None)
    ctx.user_data.pop(f"discount_pct:{plan_id}", None)
    ctx.user_data.pop(f"discount_max:{plan_id}", None)
    gp_amount, gp_code, gp_decimals = await price_for_gp_pair(effective_price, gp_chain, gp_token) if use_ghostpayments else (None, "", 0)
    if use_ghostpayments and gp_amount is None:
        if use_btcpay or (merchant_id and api_key):
            use_ghostpayments=False
        else:
            await query.edit_message_text(t("ghostpayments_no_rate", chain=gp_chain, token=gp_token), parse_mode="Markdown")
            return
    amount, code, decimals = await price_for_method(effective_price, "crypto")
    price_str = f"{fmt(gp_amount, gp_decimals, gp_code)} {gp_code}" if use_ghostpayments else f"{fmt(amount, decimals, code)} {code}"
    order_id = await db.create_order(uid, plan_id, "crypto", float(gp_amount if use_ghostpayments else amount), gp_code if use_ghostpayments else code)
    if discount_code_used:
        await db.update_order(order_id, discount_code=discount_code_used)
    if wallet_deduct>0:
        await db.update_order(order_id, wallet_credit_used=wallet_deduct)
    try:
        if use_ghostpayments:
            inv=await create_invoice_ghostpayments(gp_url, gp_key, gp_chain, gp_token, fmt(gp_amount, gp_decimals, gp_code), order_id)
            invoice_id=inv.get("invoice_id") or inv.get("id")
            pay_url=inv.get("payment_url")
        elif use_btcpay:
            inv=await create_invoice_btcpay(order_id, fmt(amount, decimals, code), code, btcpay_url, btcpay_store, btcpay_key)
            invoice_id=inv.get("id")
            pay_url=inv.get("checkoutLink")
        else:
            result = await create_invoice(order_id, fmt(amount, decimals, code), code, merchant_id, api_key)
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
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(t("btn_open_payment"), url=pay_url)]])
    await query.edit_message_text(t("crypto_invoice_created", amount=price_str), reply_markup=kb)
    asyncio.create_task(admin_event(ctx.bot, "notify_payment_link", f"🔗 User *{u.first_name}* (`{u.id}`) initiated crypto payment for plan *{plan['name']}* — {price_str}"))
    provider="ghostpayments" if use_ghostpayments else ("btcpay" if use_btcpay else "cryptomus")
    asyncio.create_task(_poll_invoice(invoice_id, order_id, u.id, merchant_id, api_key, ctx.bot, provider, btcpay_url, btcpay_store, btcpay_key, gp_url))

async def cb_buy_gp_pick(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await ensure_force_join(update, ctx):
        return
    parts = query.data.split(":", 4)
    plan_id, gp_chain, gp_token = parts[2], parts[3], parts[4]
    plan = await db.get_plan(plan_id)
    if not plan:
        await query.edit_message_text(t("order_not_found"))
        return
    gp_url = settings.GHOSTPAYMENTS_URL or await db.get_setting("ghostpayments_url", "")
    gp_key = settings.GHOSTPAYMENTS_API_KEY or await db.get_setting("ghostpayments_api_key", "")
    gp_amount, gp_code, gp_decimals = await price_for_gp_pair(plan["price"], gp_chain, gp_token)
    if gp_amount is None:
        await query.edit_message_text(t("ghostpayments_no_rate", chain=gp_chain, token=gp_token), parse_mode="Markdown")
        return
    price_str = f"{fmt(gp_amount, gp_decimals, gp_code)} {gp_code}"
    u = update.effective_user
    uid = await db.upsert_user(u.id, u.username or "", u.first_name or "")
    order_id = await db.create_order(uid, plan_id, "crypto", float(gp_amount), gp_code)
    try:
        inv = await create_invoice_ghostpayments(gp_url, gp_key, gp_chain, gp_token, fmt(gp_amount, gp_decimals, gp_code), order_id)
        invoice_id = inv.get("invoice_id") or inv.get("id")
        pay_url = inv.get("payment_url")
    except Exception as e:
        logger.error("GhostPayments invoice error: %s", e)
        await query.edit_message_text(t("ghostgate_error"))
        return
    if not invoice_id or not pay_url:
        await query.edit_message_text(t("ghostgate_error"))
        return
    await db.update_order(order_id, cryptomus_invoice_id=invoice_id)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(t("btn_open_payment"), url=pay_url)]])
    await query.edit_message_text(t("crypto_invoice_created", amount=price_str), reply_markup=kb)
    asyncio.create_task(_poll_invoice(invoice_id, order_id, u.id, "", "", ctx.bot, "ghostpayments", "", "", "", gp_url))

async def _poll_invoice(invoice_id, order_id, telegram_id, merchant_id, api_key, bot, provider="cryptomus", btcpay_url="", btcpay_store="", btcpay_key="", gp_url=""):
    for _ in range(120):
        await asyncio.sleep(30)
        try:
            order = await db.get_order(order_id)
            if not order or order["status"]!="pending":
                return
            if provider=="ghostpayments":
                result=await check_invoice_ghostpayments(gp_url, invoice_id)
                status=(result.get("status") or "").lower()
                paid=status=="completed"
                if status in ("expired", "failed"):
                    await db.update_order(order_id, status="cancelled")
                    return
            elif provider=="btcpay":
                result=await check_invoice_btcpay(invoice_id, btcpay_url, btcpay_store, btcpay_key)
                status=(result.get("status") or "").lower()
                paid=status in ("processing", "settled", "complete", "completed")
            else:
                result = await check_invoice(invoice_id, merchant_id, api_key)
                paid=result.get("result", {}).get("payment_status") in ("paid", "paid_over")
            if paid:
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
    expire_after_first_use_seconds=None
    if int(plan["days"])>0 and await db.get_setting("plan_start_after_use", "0")=="1":
        expire_after_first_use_seconds=int(plan["days"])*86400
    paid_note=await db.get_setting("paid_note", "") or None
    result = await gg.create_subscription(
        comment=user.get("first_name") or str(user["telegram_id"]),
        data_gb=plan["data_gb"],
        days=3650 if expire_after_first_use_seconds else plan["days"],
        ip_limit=plan["ip_limit"],
        node_ids=plan["node_ids"],
        expire_after_first_use_seconds=expire_after_first_use_seconds,
        note=paid_note
    )
    if not result:
        return
    sub_id = result.get("id")
    sub_url = result.get("url", "")
    now = datetime.now(timezone.utc).isoformat()
    await db.update_order(order_id, ghostgate_sub_id=sub_id, status="paid", paid_at=now)
    if order.get("discount_code"):
        await db.use_discount_code(order["discount_code"])
    if order.get("wallet_credit_used", 0)>0:
        await db.adjust_wallet(order["user_id"], -order["wallet_credit_used"])
    from bot.handlers.admin import _credit_referral_commission
    asyncio.create_task(_credit_referral_commission(order["user_id"], plan["price"], bot))
    asyncio.create_task(admin_event(bot, "notify_purchase", f"💰 *Crypto purchase confirmed*\n\n👤 {user.get('first_name','')} (`{user['telegram_id']}`)\n📦 Plan: *{plan['name']}*\n💵 Amount: {order.get('amount','')} {order.get('currency','')}"))
    u_name = f"@{user['username']}" if user.get("username") else str(user["telegram_id"])
    admin_caption = t("crypto_paid_admin", first_name=user.get("first_name",""), username=u_name, telegram_id=user["telegram_id"], plan_name=plan["name"], amount=order.get("amount",""), currency=order.get("currency",""))
    for admin_id in await db.get_all_admin_ids(settings.ADMIN_ID):
        try:
            await bot.send_message(admin_id, admin_caption, parse_mode="Markdown")
        except Exception as e:
            logger.error("Failed to notify admin %s: %s", admin_id, e)
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
    return [CallbackQueryHandler(cb_buy_crypto, pattern=r"^buy:crypto:"), CallbackQueryHandler(cb_buy_gp_pick, pattern=r"^buy:gp:")]
