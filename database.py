import aiosqlite
import logging
import json
from datetime import datetime, timedelta
from config import DB_NAME, DEFAULT_SETTINGS, TRIAL_DAYS

logger = logging.getLogger(__name__)

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS processed_invoices (invoice_id INTEGER PRIMARY KEY)")
        
        cursor = await db.execute("PRAGMA table_info(users)")
        columns_info = await cursor.fetchall()
        existing_columns = [col[1] for col in columns_info]
        
        for col_name, default_val in DEFAULT_SETTINGS.items():
            if col_name not in existing_columns:
                logger.info(f"DB Fix: Adding column '{col_name}'")
                
                col_type = "TEXT"
                if isinstance(default_val, (int, bool)): col_type = "INTEGER"
                elif isinstance(default_val, float): col_type = "REAL"
                
                sql_default = "NULL"
                if isinstance(default_val, bool): sql_default = 1 if default_val else 0
                elif isinstance(default_val, (int, float)): sql_default = default_val
                elif isinstance(default_val, str) and default_val != 'NULL': sql_default = f"'{default_val}'"
                
                try:
                    await db.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type} DEFAULT {sql_default}")
                except Exception as e:
                    logger.error(f"Migration Failed for {col_name}: {e}")

        if 'subscription_end_date' not in existing_columns:
             trial_end = (datetime.now() + timedelta(days=TRIAL_DAYS)).isoformat()
             await db.execute(f"UPDATE users SET subscription_end_date = '{trial_end}' WHERE subscription_end_date IS NULL")

        await db.commit()
    
    try:
        new_default_exchanges = json.loads(DEFAULT_SETTINGS['exchanges'])
        async with aiosqlite.connect(DB_NAME) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT user_id, exchanges FROM users")
            rows = await cursor.fetchall()
            
            for row in rows:
                try:
                    user_exchanges = json.loads(row['exchanges'])
                    updated = False
                    for exc in new_default_exchanges:
                        if exc not in user_exchanges:
                            user_exchanges.append(exc)
                            updated = True
                    
                    if updated:
                        await db.execute("UPDATE users SET exchanges = ? WHERE user_id = ?", 
                                         (json.dumps(user_exchanges), row['user_id']))
                except:
                    await db.execute("UPDATE users SET exchanges = ? WHERE user_id = ?", 
                                     (DEFAULT_SETTINGS['exchanges'], row['user_id']))
            await db.commit()
    except Exception as e:
        logger.error(f"Exchanges Migration Error: {e}")

async def is_invoice_processed(invoice_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT 1 FROM processed_invoices WHERE invoice_id = ?", (invoice_id,))
        return await cursor.fetchone() is not None

async def mark_invoice_processed(invoice_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO processed_invoices (invoice_id) VALUES (?)", (invoice_id,))
        await db.commit()

async def get_user_settings(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        if row: return dict(row)
        return None

async def register_user(user_id, trial_days=TRIAL_DAYS, referrer_id=0):
    async with aiosqlite.connect(DB_NAME) as db:
        cols = list(DEFAULT_SETTINGS.keys())
        vals = []
        trial_end = (datetime.now() + timedelta(days=trial_days)).isoformat()
        
        for k, v in DEFAULT_SETTINGS.items():
            if k == 'subscription_end_date': vals.append(trial_end)
            elif k == 'referrer_id': vals.append(referrer_id)
            elif isinstance(v, bool): vals.append(1 if v else 0)
            else: vals.append(v)
        
        placeholders = ', '.join(['?'] * (len(cols) + 1))
        await db.execute(f"INSERT OR IGNORE INTO users (user_id, {', '.join(cols)}) VALUES ({placeholders})", [user_id, *vals])
        await db.commit()

async def add_subscription_days(user_id, days):
    user = await get_user_settings(user_id)
    if not user: return None
    
    current_end_str = user.get('subscription_end_date')
    now = datetime.now()
    
    try:
        current_end = datetime.fromisoformat(current_end_str)
        if current_end > now: new_end = current_end + timedelta(days=days)
        else: new_end = now + timedelta(days=days)
    except: new_end = now + timedelta(days=days)
        
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET subscription_end_date = ? WHERE user_id = ?", (new_end.isoformat(), user_id))
        await db.commit()
    return new_end

async def update_user_setting(user_id, column, value):
    async with aiosqlite.connect(DB_NAME) as db:
        if isinstance(value, bool): value = 1 if value else 0
        await db.execute(f"UPDATE users SET {column} = ? WHERE user_id = ?", (value, user_id))
        await db.commit()

async def get_all_users():
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users")
        return [dict(row) for row in await cursor.fetchall()]