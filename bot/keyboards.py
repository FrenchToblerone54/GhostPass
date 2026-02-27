from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from bot.strings import t

def _fmt_plan_price(price, base_currency):
    if base_currency=="IRT":
        try:
            i=int(float(price))
            if float(price)==i and i>=1000 and i%1000==0:
                return f"{i//1000}k"
        except Exception:
            pass
    return str(price)

def main_consumer_kb(show_trial=False):
    rows = [[t("btn_consumer_plans"), t("btn_consumer_status")], [t("btn_consumer_support")]]
    if show_trial:
        rows.insert(0, [t("btn_consumer_trial")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def main_admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("btn_adm_subs"), callback_data="adm:subs"), InlineKeyboardButton(t("btn_adm_plans"), callback_data="adm:plans")],
        [InlineKeyboardButton(t("btn_adm_users"), callback_data="adm:users"), InlineKeyboardButton(t("btn_adm_admins"), callback_data="adm:admins")],
        [InlineKeyboardButton(t("btn_adm_orders"), callback_data="adm:orders"), InlineKeyboardButton(t("btn_adm_settings"), callback_data="adm:settings")],
        [InlineKeyboardButton(t("btn_adm_update"), callback_data="adm:update")],
    ])

def back_kb(target):
    return InlineKeyboardMarkup([[InlineKeyboardButton(t("btn_back"), callback_data=target)]])

def confirm_reject_kb(order_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(t("btn_confirm"), callback_data=f"order:confirm:{order_id}"),
        InlineKeyboardButton(t("btn_reject"), callback_data=f"order:reject:{order_id}"),
    ]])

def plan_buy_kb(plan_id, card_enabled, crypto_enabled, requests_enabled, manual_enabled):
    rows = []
    if card_enabled:
        rows.append([InlineKeyboardButton(t("btn_pay_card"), callback_data=f"buy:card:{plan_id}")])
    if crypto_enabled:
        rows.append([InlineKeyboardButton(t("btn_pay_crypto"), callback_data=f"buy:crypto:{plan_id}")])
    if requests_enabled:
        rows.append([InlineKeyboardButton(t("btn_request_sub"), callback_data=f"buy:request:{plan_id}")])
    if manual_enabled:
        rows.append([InlineKeyboardButton(t("btn_pay_manual"), callback_data=f"buy:manual:{plan_id}")])
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data="consumer:plans")])
    return InlineKeyboardMarkup(rows)

def plans_kb(plans, base_currency="IRT"):
    rows = [[InlineKeyboardButton(f"{t('btn_buy_plan', name=p['name'])} — {_fmt_plan_price(p['price'], base_currency)} {base_currency}", callback_data=f"plan:{p['id']}")] for p in plans]
    return InlineKeyboardMarkup(rows)

def settings_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("btn_set_gg"), callback_data="set:gg_url")],
        [InlineKeyboardButton(t("btn_set_card"), callback_data="set:card")],
        [InlineKeyboardButton(t("btn_set_crypto"), callback_data="set:crypto")],
        [InlineKeyboardButton(t("btn_set_requests"), callback_data="set:requests")],
        [InlineKeyboardButton(t("btn_set_support"), callback_data="set:support")],
        [InlineKeyboardButton(t("btn_set_currencies"), callback_data="set:currencies")],
        [InlineKeyboardButton(t("btn_set_usdt"), callback_data="set:usdt")],
        [InlineKeyboardButton(t("btn_set_trial"), callback_data="set:trial")],
        [InlineKeyboardButton(t("btn_set_sync"), callback_data="set:sync")],
        [InlineKeyboardButton(t("btn_set_force_join"), callback_data="set:force_join")],
        [InlineKeyboardButton(t("btn_set_plan_start_after_use"), callback_data="set:plan_start_after_use")],
        [InlineKeyboardButton(t("btn_set_trial_start_after_use"), callback_data="set:trial_start_after_use")],
        [InlineKeyboardButton(t("btn_set_update_http_proxy"), callback_data="set:update_http_proxy"), InlineKeyboardButton(t("btn_set_update_https_proxy"), callback_data="set:update_https_proxy")],
        [InlineKeyboardButton(t("btn_back"), callback_data="adm:back")],
    ])

def currencies_kb(currencies, base_currency, back_cb):
    rows = [[InlineKeyboardButton(f"{'📌 ' if c['code']==base_currency else ''}{c['code']} — {c['name']}", callback_data=f"curr:detail:{c['code']}")] for c in currencies]
    rows.append([InlineKeyboardButton(t("btn_curr_add"), callback_data="curr:add"), InlineKeyboardButton(t("btn_curr_set_base"), callback_data="curr:set_base")])
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)

def method_select_kb(selected_methods, done_cb, back_cb):
    all_methods = [("card", t("btn_method_card")), ("crypto", t("btn_method_crypto")), ("request", t("btn_method_request")), ("manual", t("btn_method_manual"))]
    rows = []
    for code, label in all_methods:
        check = "✅" if code in selected_methods else "⬜"
        rows.append([InlineKeyboardButton(f"{check} {label}", callback_data=f"meth_toggle:{code}")])
    rows.append([InlineKeyboardButton(t("btn_done"), callback_data=done_cb), InlineKeyboardButton(t("btn_back"), callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)

def node_select_kb(nodes, selected_ids, done_cb, back_cb, all_cb="", none_cb=""):
    rows = []
    for node in nodes:
        for inbound in node.get("inbounds", []):
            label = inbound.get("name") or f"Inbound #{inbound['id']}"
            check = "✅" if inbound["id"] in selected_ids else "⬜"
            rows.append([InlineKeyboardButton(f"{check} {node['name']} / {label}", callback_data=f"node_toggle:{inbound['id']}")])
    if all_cb and none_cb:
        rows.append([InlineKeyboardButton(t("btn_select_all"), callback_data=all_cb), InlineKeyboardButton(t("btn_unselect_all"), callback_data=none_cb)])
    rows.append([InlineKeyboardButton(t("btn_done"), callback_data=done_cb), InlineKeyboardButton(t("btn_back"), callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)

def skip_kb(skip_cb, back_cb=None):
    row = [InlineKeyboardButton(t("btn_skip"), callback_data=skip_cb)]
    if back_cb:
        row.append(InlineKeyboardButton(t("btn_back"), callback_data=back_cb))
    return InlineKeyboardMarkup([row])

def yes_no_kb(yes_cb, no_cb):
    return InlineKeyboardMarkup([[InlineKeyboardButton(t("btn_yes"), callback_data=yes_cb), InlineKeyboardButton(t("btn_no"), callback_data=no_cb)]])

def cancel_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton(t("btn_cancel"), callback_data="cancel")]])

def sub_actions_kb(sub_id, back_cb):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("btn_sub_stats"), callback_data=f"sub:stats:{sub_id}")],
        [InlineKeyboardButton(t("btn_delete"), callback_data=f"sub:delete:{sub_id}")],
        [InlineKeyboardButton(t("btn_back"), callback_data=back_cb)],
    ])

def user_actions_kb(uid, is_banned, back_cb):
    ban_label = t("btn_unban") if is_banned else t("btn_ban")
    ban_cb = f"user:unban:{uid}" if is_banned else f"user:ban:{uid}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(ban_label, callback_data=ban_cb)],
        [InlineKeyboardButton(t("btn_adm_orders"), callback_data=f"user:orders:{uid}")],
        [InlineKeyboardButton(t("btn_back"), callback_data=back_cb)],
    ])

def plan_actions_kb(plan_id, is_active):
    toggle_label = t("btn_deactivate") if is_active else t("btn_activate")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label, callback_data=f"plan:toggle:{plan_id}")],
        [InlineKeyboardButton(t("btn_edit_price"), callback_data=f"plan:edit_price:{plan_id}"), InlineKeyboardButton(t("btn_edit_name"), callback_data=f"plan:edit_name:{plan_id}")],
        [InlineKeyboardButton(t("btn_edit_nodes"), callback_data=f"plan:edit_nodes:{plan_id}")],
        [InlineKeyboardButton(t("btn_delete"), callback_data=f"plan:delete:{plan_id}")],
        [InlineKeyboardButton(t("btn_back"), callback_data="adm:plans")],
    ])

def order_detail_kb(order_id, status, back_cb):
    rows = []
    if status in ("pending", "waiting_confirm"):
        rows.append([InlineKeyboardButton(t("btn_confirm"), callback_data=f"order:confirm:{order_id}"), InlineKeyboardButton(t("btn_reject"), callback_data=f"order:reject:{order_id}")])
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)

def curr_detail_kb(code, is_base, back_cb):
    rows = []
    if not is_base:
        rows.append([InlineKeyboardButton(t("btn_edit_rate"), callback_data=f"curr:edit_rate:{code}")])
    rows.append([InlineKeyboardButton(t("btn_delete"), callback_data=f"curr:delete:{code}")])
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)

def base_select_kb(currencies, back_cb):
    rows = [[InlineKeyboardButton(f"{c['code']} — {c['name']}", callback_data=f"curr:make_base:{c['code']}")] for c in currencies]
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)
