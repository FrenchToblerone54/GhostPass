import aiosqlite
import json
from nanoid import generate
from config import settings

SCHEMA_VERSION = 1

async def _open():
    db = await aiosqlite.connect(settings.DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db

async def init_db():
    db = await _open()
    async with db:
        await db.executescript("""
CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    telegram_id INTEGER UNIQUE NOT NULL,
    username    TEXT,
    first_name  TEXT,
    is_banned   INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS plans (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    data_gb     REAL NOT NULL,
    days        INTEGER NOT NULL,
    ip_limit    INTEGER NOT NULL DEFAULT 1,
    price       REAL NOT NULL,
    node_ids    TEXT NOT NULL DEFAULT '[]',
    is_active   INTEGER DEFAULT 1,
    sort_order  INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS orders (
    id                   TEXT PRIMARY KEY,
    user_id              TEXT NOT NULL REFERENCES users(id),
    plan_id              TEXT NOT NULL REFERENCES plans(id),
    ghostgate_sub_id     TEXT,
    payment_method       TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'pending',
    amount               REAL NOT NULL,
    currency             TEXT NOT NULL,
    cryptomus_invoice_id TEXT,
    receipt_file_id      TEXT,
    created_at           TEXT DEFAULT (datetime('now')),
    paid_at              TEXT
);
CREATE TABLE IF NOT EXISTS admins (
    telegram_id INTEGER PRIMARY KEY,
    added_by    INTEGER NOT NULL,
    permissions TEXT NOT NULL DEFAULT '["view"]',
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
""")
        await db.commit()

async def upsert_user(telegram_id, username, first_name):
    db = await _open()
    async with db:
        row = await (await db.execute("SELECT id FROM users WHERE telegram_id=?", (telegram_id,))).fetchone()
        if row:
            await db.execute("UPDATE users SET username=?, first_name=? WHERE telegram_id=?", (username, first_name, telegram_id))
            await db.commit()
            return row["id"]
        uid = generate(size=20)
        await db.execute("INSERT INTO users (id, telegram_id, username, first_name) VALUES (?,?,?,?)", (uid, telegram_id, username, first_name))
        await db.commit()
        return uid

async def get_user_by_telegram(telegram_id):
    db = await _open()
    async with db:
        row = await (await db.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,))).fetchone()
        return dict(row) if row else None

async def get_user_by_id(uid):
    db = await _open()
    async with db:
        row = await (await db.execute("SELECT * FROM users WHERE id=?", (uid,))).fetchone()
        return dict(row) if row else None

async def ban_user(telegram_id, ban=True):
    db = await _open()
    async with db:
        await db.execute("UPDATE users SET is_banned=? WHERE telegram_id=?", (int(ban), telegram_id))
        await db.commit()

async def search_users(query):
    db = await _open()
    async with db:
        rows = await (await db.execute(
            "SELECT * FROM users WHERE CAST(telegram_id AS TEXT) LIKE ? OR username LIKE ? OR first_name LIKE ? LIMIT 20",
            (f"%{query}%", f"%{query}%", f"%{query}%")
        )).fetchall()
        return [dict(r) for r in rows]

async def list_users(offset=0, limit=20):
    db = await _open()
    async with db:
        rows = await (await db.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset))).fetchall()
        total = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
        return [dict(r) for r in rows], total

async def create_plan(name, data_gb, days, ip_limit, price, node_ids):
    db = await _open()
    async with db:
        cnt = (await (await db.execute("SELECT COUNT(*) FROM plans")).fetchone())[0]
        pid = generate(size=20)
        await db.execute(
            "INSERT INTO plans (id, name, data_gb, days, ip_limit, price, node_ids, sort_order) VALUES (?,?,?,?,?,?,?,?)",
            (pid, name, data_gb, days, ip_limit, price, json.dumps(node_ids), cnt)
        )
        await db.commit()
        return pid

async def get_plan(plan_id):
    db = await _open()
    async with db:
        row = await (await db.execute("SELECT * FROM plans WHERE id=?", (plan_id,))).fetchone()
        if not row:
            return None
        d = dict(row)
        d["node_ids"] = json.loads(d["node_ids"])
        return d

async def list_plans(active_only=True):
    db = await _open()
    async with db:
        q = "SELECT * FROM plans WHERE is_active=1 ORDER BY sort_order, created_at" if active_only else "SELECT * FROM plans ORDER BY sort_order, created_at"
        rows = await (await db.execute(q)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["node_ids"] = json.loads(d["node_ids"])
            result.append(d)
        return result

async def update_plan(plan_id, **kwargs):
    allowed = {"name", "data_gb", "days", "ip_limit", "price", "node_ids", "is_active", "sort_order"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if "node_ids" in fields:
        fields["node_ids"] = json.dumps(fields["node_ids"])
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    db = await _open()
    async with db:
        await db.execute(f"UPDATE plans SET {sets} WHERE id=?", (*fields.values(), plan_id))
        await db.commit()

async def delete_plan(plan_id):
    db = await _open()
    async with db:
        await db.execute("DELETE FROM plans WHERE id=?", (plan_id,))
        await db.commit()

async def create_order(user_id, plan_id, payment_method, amount, currency):
    db = await _open()
    async with db:
        oid = generate(size=20)
        await db.execute(
            "INSERT INTO orders (id, user_id, plan_id, payment_method, amount, currency) VALUES (?,?,?,?,?,?)",
            (oid, user_id, plan_id, payment_method, amount, currency)
        )
        await db.commit()
        return oid

async def get_order(order_id):
    db = await _open()
    async with db:
        row = await (await db.execute("SELECT * FROM orders WHERE id=?", (order_id,))).fetchone()
        return dict(row) if row else None

async def update_order(order_id, **kwargs):
    allowed = {"ghostgate_sub_id", "payment_method", "status", "cryptomus_invoice_id", "receipt_file_id", "paid_at"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    db = await _open()
    async with db:
        await db.execute(f"UPDATE orders SET {sets} WHERE id=?", (*fields.values(), order_id))
        await db.commit()

async def get_user_paid_orders(user_id):
    db = await _open()
    async with db:
        rows = await (await db.execute(
            "SELECT o.*, p.name as plan_name, p.data_gb, p.days FROM orders o JOIN plans p ON o.plan_id=p.id WHERE o.user_id=? AND o.status='paid' ORDER BY o.paid_at DESC",
            (user_id,)
        )).fetchall()
        return [dict(r) for r in rows]

async def get_pending_orders():
    db = await _open()
    async with db:
        rows = await (await db.execute(
            "SELECT o.*, u.first_name, u.username, u.telegram_id, p.name as plan_name FROM orders o JOIN users u ON o.user_id=u.id JOIN plans p ON o.plan_id=p.id WHERE o.status IN ('pending','waiting_confirm') ORDER BY o.created_at",
        )).fetchall()
        return [dict(r) for r in rows]

async def list_orders(status=None, offset=0, limit=20):
    db = await _open()
    async with db:
        if status:
            rows = await (await db.execute(
                "SELECT o.*, u.first_name, u.username, u.telegram_id, p.name as plan_name FROM orders o JOIN users u ON o.user_id=u.id JOIN plans p ON o.plan_id=p.id WHERE o.status=? ORDER BY o.created_at DESC LIMIT ? OFFSET ?",
                (status, limit, offset)
            )).fetchall()
            total = (await (await db.execute("SELECT COUNT(*) FROM orders WHERE status=?", (status,))).fetchone())[0]
        else:
            rows = await (await db.execute(
                "SELECT o.*, u.first_name, u.username, u.telegram_id, p.name as plan_name FROM orders o JOIN users u ON o.user_id=u.id JOIN plans p ON o.plan_id=p.id ORDER BY o.created_at DESC LIMIT ? OFFSET ?",
                (limit, offset)
            )).fetchall()
            total = (await (await db.execute("SELECT COUNT(*) FROM orders")).fetchone())[0]
        return [dict(r) for r in rows], total

async def get_paid_orders_with_sub():
    db = await _open()
    async with db:
        rows = await (await db.execute(
            "SELECT o.*, u.telegram_id FROM orders o JOIN users u ON o.user_id=u.id WHERE o.status='paid' AND o.ghostgate_sub_id IS NOT NULL"
        )).fetchall()
        return [dict(r) for r in rows]

async def get_orders_by_user(user_id):
    db = await _open()
    async with db:
        rows = await (await db.execute(
            "SELECT o.*, p.name as plan_name FROM orders o JOIN plans p ON o.plan_id=p.id WHERE o.user_id=? ORDER BY o.created_at DESC",
            (user_id,)
        )).fetchall()
        return [dict(r) for r in rows]

async def is_admin(telegram_id, root_id):
    if telegram_id==root_id:
        return True
    db = await _open()
    async with db:
        row = await (await db.execute("SELECT 1 FROM admins WHERE telegram_id=?", (telegram_id,))).fetchone()
        return row is not None

async def list_admins():
    db = await _open()
    async with db:
        rows = await (await db.execute("SELECT * FROM admins ORDER BY created_at")).fetchall()
        return [dict(r) for r in rows]

async def add_admin(telegram_id, added_by, permissions=None):
    db = await _open()
    async with db:
        perms = json.dumps(permissions or ["view"])
        await db.execute("INSERT OR REPLACE INTO admins (telegram_id, added_by, permissions) VALUES (?,?,?)", (telegram_id, added_by, perms))
        await db.commit()

async def remove_admin(telegram_id):
    db = await _open()
    async with db:
        await db.execute("DELETE FROM admins WHERE telegram_id=?", (telegram_id,))
        await db.commit()

async def get_all_admin_ids(root_id):
    db = await _open()
    async with db:
        rows = await (await db.execute("SELECT telegram_id FROM admins")).fetchall()
        ids = [r[0] for r in rows]
        if root_id not in ids:
            ids.insert(0, root_id)
        return ids

async def get_setting(key, default=None):
    db = await _open()
    async with db:
        row = await (await db.execute("SELECT value FROM settings WHERE key=?", (key,))).fetchone()
        return row[0] if row else default

async def set_setting(key, value):
    db = await _open()
    async with db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, str(value) if value is not None else None))
        await db.commit()

async def get_all_settings():
    db = await _open()
    async with db:
        rows = await (await db.execute("SELECT key, value FROM settings")).fetchall()
        return {r["key"]: r["value"] for r in rows}

async def get_orders_by_invoice(invoice_id):
    db = await _open()
    async with db:
        row = await (await db.execute("SELECT * FROM orders WHERE cryptomus_invoice_id=?", (invoice_id,))).fetchone()
        return dict(row) if row else None
