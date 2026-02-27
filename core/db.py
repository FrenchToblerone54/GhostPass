import sqlite3
import json
import asyncio
from contextlib import contextmanager
from nanoid import generate
from config import settings

@contextmanager
def _open():
    db = sqlite3.connect(settings.DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
    finally:
        db.close()

def _migrate_v1(db):
    db.executescript("""
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
CREATE TABLE IF NOT EXISTS trial_claims (
    user_id          TEXT PRIMARY KEY REFERENCES users(id),
    claimed_at       TEXT DEFAULT (datetime('now')),
    ghostgate_sub_id TEXT
);
PRAGMA user_version=1;
""")

async def init_db():
    def _sync():
        with _open() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version < 1:
                _migrate_v1(db)
    await asyncio.to_thread(_sync)

async def upsert_user(telegram_id, username, first_name):
    def _sync():
        with _open() as db:
            row = db.execute("SELECT id FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
            if row:
                db.execute("UPDATE users SET username=?, first_name=? WHERE telegram_id=?", (username, first_name, telegram_id))
                db.commit()
                return row["id"]
            uid = generate(size=20)
            db.execute("INSERT INTO users (id, telegram_id, username, first_name) VALUES (?,?,?,?)", (uid, telegram_id, username, first_name))
            db.commit()
            return uid
    return await asyncio.to_thread(_sync)

async def get_user_by_telegram(telegram_id):
    def _sync():
        with _open() as db:
            row = db.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
            return dict(row) if row else None
    return await asyncio.to_thread(_sync)

async def get_user_by_id(uid):
    def _sync():
        with _open() as db:
            row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            return dict(row) if row else None
    return await asyncio.to_thread(_sync)

async def ban_user(telegram_id, ban=True):
    def _sync():
        with _open() as db:
            db.execute("UPDATE users SET is_banned=? WHERE telegram_id=?", (int(ban), telegram_id))
            db.commit()
    await asyncio.to_thread(_sync)

async def search_users(query):
    def _sync():
        with _open() as db:
            rows = db.execute(
                "SELECT * FROM users WHERE CAST(telegram_id AS TEXT) LIKE ? OR username LIKE ? OR first_name LIKE ? LIMIT 20",
                (f"%{query}%", f"%{query}%", f"%{query}%")
            ).fetchall()
            return [dict(r) for r in rows]
    return await asyncio.to_thread(_sync)

async def list_users(offset=0, limit=20):
    def _sync():
        with _open() as db:
            rows = db.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
            total = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            return [dict(r) for r in rows], total
    return await asyncio.to_thread(_sync)

async def create_plan(name, data_gb, days, ip_limit, price, node_ids):
    def _sync():
        with _open() as db:
            cnt = db.execute("SELECT COUNT(*) FROM plans").fetchone()[0]
            pid = generate(size=20)
            db.execute(
                "INSERT INTO plans (id, name, data_gb, days, ip_limit, price, node_ids, sort_order) VALUES (?,?,?,?,?,?,?,?)",
                (pid, name, data_gb, days, ip_limit, price, json.dumps(node_ids), cnt)
            )
            db.commit()
            return pid
    return await asyncio.to_thread(_sync)

async def get_plan(plan_id):
    def _sync():
        with _open() as db:
            row = db.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
            if not row:
                return None
            d = dict(row)
            d["node_ids"] = json.loads(d["node_ids"])
            return d
    return await asyncio.to_thread(_sync)

async def list_plans(active_only=True):
    def _sync():
        with _open() as db:
            q = "SELECT * FROM plans WHERE is_active=1 ORDER BY sort_order, created_at" if active_only else "SELECT * FROM plans ORDER BY sort_order, created_at"
            rows = db.execute(q).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["node_ids"] = json.loads(d["node_ids"])
                result.append(d)
            return result
    return await asyncio.to_thread(_sync)

async def update_plan(plan_id, **kwargs):
    allowed = {"name", "data_gb", "days", "ip_limit", "price", "node_ids", "is_active", "sort_order"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if "node_ids" in fields:
        fields["node_ids"] = json.dumps(fields["node_ids"])
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    def _sync():
        with _open() as db:
            db.execute(f"UPDATE plans SET {sets} WHERE id=?", (*fields.values(), plan_id))
            db.commit()
    await asyncio.to_thread(_sync)

async def delete_plan(plan_id):
    def _sync():
        with _open() as db:
            db.execute("DELETE FROM plans WHERE id=?", (plan_id,))
            db.commit()
    await asyncio.to_thread(_sync)

async def create_order(user_id, plan_id, payment_method, amount, currency):
    def _sync():
        with _open() as db:
            oid = generate(size=20)
            db.execute(
                "INSERT INTO orders (id, user_id, plan_id, payment_method, amount, currency) VALUES (?,?,?,?,?,?)",
                (oid, user_id, plan_id, payment_method, amount, currency)
            )
            db.commit()
            return oid
    return await asyncio.to_thread(_sync)

async def get_order(order_id):
    def _sync():
        with _open() as db:
            row = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            return dict(row) if row else None
    return await asyncio.to_thread(_sync)

async def update_order(order_id, **kwargs):
    allowed = {"ghostgate_sub_id", "payment_method", "status", "cryptomus_invoice_id", "receipt_file_id", "paid_at"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    def _sync():
        with _open() as db:
            db.execute(f"UPDATE orders SET {sets} WHERE id=?", (*fields.values(), order_id))
            db.commit()
    await asyncio.to_thread(_sync)

async def get_user_paid_orders(user_id):
    def _sync():
        with _open() as db:
            rows = db.execute(
                "SELECT o.*, p.name as plan_name, p.data_gb, p.days FROM orders o JOIN plans p ON o.plan_id=p.id WHERE o.user_id=? AND o.status='paid' ORDER BY o.paid_at DESC",
                (user_id,)
            ).fetchall()
            return [dict(r) for r in rows]
    return await asyncio.to_thread(_sync)

async def get_pending_orders():
    def _sync():
        with _open() as db:
            rows = db.execute(
                "SELECT o.*, u.first_name, u.username, u.telegram_id, p.name as plan_name FROM orders o JOIN users u ON o.user_id=u.id JOIN plans p ON o.plan_id=p.id WHERE o.status IN ('pending','waiting_confirm') ORDER BY o.created_at"
            ).fetchall()
            return [dict(r) for r in rows]
    return await asyncio.to_thread(_sync)

async def list_orders(status=None, offset=0, limit=20):
    def _sync():
        with _open() as db:
            if status:
                rows = db.execute(
                    "SELECT o.*, u.first_name, u.username, u.telegram_id, p.name as plan_name FROM orders o JOIN users u ON o.user_id=u.id JOIN plans p ON o.plan_id=p.id WHERE o.status=? ORDER BY o.created_at DESC LIMIT ? OFFSET ?",
                    (status, limit, offset)
                ).fetchall()
                total = db.execute("SELECT COUNT(*) FROM orders WHERE status=?", (status,)).fetchone()[0]
            else:
                rows = db.execute(
                    "SELECT o.*, u.first_name, u.username, u.telegram_id, p.name as plan_name FROM orders o JOIN users u ON o.user_id=u.id JOIN plans p ON o.plan_id=p.id ORDER BY o.created_at DESC LIMIT ? OFFSET ?",
                    (limit, offset)
                ).fetchall()
                total = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            return [dict(r) for r in rows], total
    return await asyncio.to_thread(_sync)

async def get_paid_orders_with_sub():
    def _sync():
        with _open() as db:
            rows = db.execute(
                "SELECT o.*, u.telegram_id FROM orders o JOIN users u ON o.user_id=u.id WHERE o.status='paid' AND o.ghostgate_sub_id IS NOT NULL"
            ).fetchall()
            return [dict(r) for r in rows]
    return await asyncio.to_thread(_sync)

async def get_orders_by_user(user_id):
    def _sync():
        with _open() as db:
            rows = db.execute(
                "SELECT o.*, p.name as plan_name FROM orders o JOIN plans p ON o.plan_id=p.id WHERE o.user_id=? ORDER BY o.created_at DESC",
                (user_id,)
            ).fetchall()
            return [dict(r) for r in rows]
    return await asyncio.to_thread(_sync)

async def is_admin(telegram_id, root_id):
    if telegram_id==root_id:
        return True
    def _sync():
        with _open() as db:
            row = db.execute("SELECT 1 FROM admins WHERE telegram_id=?", (telegram_id,)).fetchone()
            return row is not None
    return await asyncio.to_thread(_sync)

async def list_admins():
    def _sync():
        with _open() as db:
            rows = db.execute("SELECT * FROM admins ORDER BY created_at").fetchall()
            return [dict(r) for r in rows]
    return await asyncio.to_thread(_sync)

async def add_admin(telegram_id, added_by, permissions=None):
    def _sync():
        with _open() as db:
            perms = json.dumps(permissions or ["view"])
            db.execute("INSERT OR REPLACE INTO admins (telegram_id, added_by, permissions) VALUES (?,?,?)", (telegram_id, added_by, perms))
            db.commit()
    await asyncio.to_thread(_sync)

async def remove_admin(telegram_id):
    def _sync():
        with _open() as db:
            db.execute("DELETE FROM admins WHERE telegram_id=?", (telegram_id,))
            db.commit()
    await asyncio.to_thread(_sync)

async def get_all_admin_ids(root_id):
    def _sync():
        with _open() as db:
            rows = db.execute("SELECT telegram_id FROM admins").fetchall()
            ids = [r[0] for r in rows]
            if root_id not in ids:
                ids.insert(0, root_id)
            return ids
    return await asyncio.to_thread(_sync)

async def get_setting(key, default=None):
    def _sync():
        with _open() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return row[0] if row else default
    return await asyncio.to_thread(_sync)

async def set_setting(key, value):
    def _sync():
        with _open() as db:
            db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, str(value) if value is not None else None))
            db.commit()
    await asyncio.to_thread(_sync)

async def get_all_settings():
    def _sync():
        with _open() as db:
            rows = db.execute("SELECT key, value FROM settings").fetchall()
            return {r["key"]: r["value"] for r in rows}
    return await asyncio.to_thread(_sync)

async def has_trial_claim(user_id):
    def _sync():
        with _open() as db:
            row = db.execute("SELECT 1 FROM trial_claims WHERE user_id=?", (user_id,)).fetchone()
            return row is not None
    return await asyncio.to_thread(_sync)

async def create_trial_claim(user_id, ghostgate_sub_id):
    def _sync():
        with _open() as db:
            db.execute("INSERT INTO trial_claims (user_id, ghostgate_sub_id) VALUES (?,?)", (user_id, str(ghostgate_sub_id)))
            db.commit()
    await asyncio.to_thread(_sync)

async def update_ghostgate_sub_id(old_sub_id, new_sub_id):
    def _sync():
        with _open() as db:
            db.execute("UPDATE orders SET ghostgate_sub_id=? WHERE ghostgate_sub_id=?", (new_sub_id, old_sub_id))
            db.execute("UPDATE trial_claims SET ghostgate_sub_id=? WHERE ghostgate_sub_id=?", (new_sub_id, old_sub_id))
            db.commit()
    await asyncio.to_thread(_sync)

async def get_orders_by_invoice(invoice_id):
    def _sync():
        with _open() as db:
            row = db.execute("SELECT * FROM orders WHERE cryptomus_invoice_id=?", (invoice_id,)).fetchone()
            return dict(row) if row else None
    return await asyncio.to_thread(_sync)
