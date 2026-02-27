import logging
from decimal import Decimal
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, ConversationHandler, filters
import core.db as db
from core.currency import price_for_method, fmt
from bot.strings import t
from bot.keyboards import confirm_reject_kb, cancel_kb
from bot.states import USDT_MANUAL_TX
from config import settings

logger=logging.getLogger(__name__)

async def _addresses():
    return {
        "TRC20": settings.USDT_TRC20_ADDRESS or await db.get_setting("usdt_trc20_address", ""),
        "BSC": settings.USDT_BSC_ADDRESS or await db.get_setting("usdt_bsc_address", ""),
        "POLYGON": settings.USDT_POLYGON_ADDRESS or await db.get_setting("usdt_polygon_address", ""),
    }

async def cb_buy_manual(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    plan_id=query.data.split(":", 2)[2]
    plan=await db.get_plan(plan_id)
    if not plan:
        await query.edit_message_text(t("order_not_found"))
        return ConversationHandler.END
    addresses=await _addresses()
    available={k: v for k, v in addresses.items() if v}
    if not available:
        await query.edit_message_text(t("manual_no_address"))
        return ConversationHandler.END
    amount, code, decimals=await price_for_method(plan["price"], "manual")
    u=update.effective_user
    uid=await db.upsert_user(u.id, u.username or "", u.first_name or "")
    order_id=await db.create_order(uid, plan_id, "manual", float(amount), code)
    amount_str=f"{fmt(Decimal(str(amount)), decimals, code)} {code}"
    ctx.user_data["manual_order_id"]=order_id
    ctx.user_data["manual_amount_str"]=amount_str
    ctx.user_data["manual_plan_name"]=plan["name"]
    rows=[]
    for chain in ("TRC20", "BSC", "POLYGON"):
        if available.get(chain):
            rows.append([InlineKeyboardButton(chain, callback_data=f"manual:chain:{chain}")])
    rows.append([InlineKeyboardButton(t("btn_cancel"), callback_data="cancel")])
    await query.edit_message_text(t("manual_chain_prompt", amount=amount_str), reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")
    return USDT_MANUAL_TX

async def cb_select_chain(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    chain=query.data.split(":", 2)[2]
    addresses=await _addresses()
    address=addresses.get(chain, "")
    if not address:
        await query.edit_message_text(t("manual_no_address"))
        return ConversationHandler.END
    ctx.user_data["manual_chain"]=chain
    ctx.user_data["manual_address"]=address
    await query.edit_message_text(
        t("manual_send_proof", chain=chain, amount=ctx.user_data.get("manual_amount_str", "-"), address=address),
        reply_markup=cancel_kb(),
        parse_mode="Markdown"
    )
    return USDT_MANUAL_TX

async def handle_tx_hash(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    order_id=ctx.user_data.get("manual_order_id")
    chain=ctx.user_data.get("manual_chain")
    address=ctx.user_data.get("manual_address")
    amount_str=ctx.user_data.get("manual_amount_str", "")
    plan_name=ctx.user_data.get("manual_plan_name", "")
    if not order_id or not chain or not address:
        return ConversationHandler.END
    tx_hash=update.message.text.strip()
    if len(tx_hash)<16:
        await update.message.reply_text(t("invalid_input"))
        return USDT_MANUAL_TX
    await db.update_order(order_id, status="waiting_confirm", cryptomus_invoice_id=f"{chain}:{tx_hash}")
    u=update.effective_user
    caption=t(
        "manual_request_caption",
        first_name=u.first_name or "",
        username=f"@{u.username.lstrip('@')}" if u.username else str(u.id),
        telegram_id=u.id,
        plan_name=plan_name,
        amount=amount_str
    )+f"\n🔗 Chain: {chain}\n🏦 Address: `{address}`\n🧾 Tx: `{tx_hash}`"
    admin_ids=await db.get_all_admin_ids(settings.ADMIN_ID)
    for admin_id in admin_ids:
        try:
            await ctx.bot.send_message(admin_id, caption, reply_markup=confirm_reject_kb(order_id), parse_mode="Markdown")
        except Exception as e:
            logger.error("Failed to notify admin %s: %s", admin_id, e)
    for k in ("manual_order_id", "manual_chain", "manual_address", "manual_amount_str", "manual_plan_name"):
        ctx.user_data.pop(k, None)
    await update.message.reply_text(t("manual_proof_received"))
    return ConversationHandler.END

async def cb_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    order_id=ctx.user_data.pop("manual_order_id", None)
    for k in ("manual_chain", "manual_address", "manual_amount_str", "manual_plan_name"):
        ctx.user_data.pop(k, None)
    if order_id:
        await db.update_order(order_id, status="cancelled")
    await query.edit_message_text(t("adm_cancelled"))
    return ConversationHandler.END

def get_handlers():
    return [
        ConversationHandler(
            entry_points=[CallbackQueryHandler(cb_buy_manual, pattern=r"^buy:manual:")],
            states={
                USDT_MANUAL_TX: [
                    CallbackQueryHandler(cb_select_chain, pattern=r"^manual:chain:"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_tx_hash),
                ],
            },
            fallbacks=[CallbackQueryHandler(cb_cancel, pattern=r"^cancel$")],
            per_message=False,
        )
    ]
