import os, sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
PG = DATABASE_URL.startswith(('postgres://', 'postgresql://'))

@contextmanager
def connect():
    if PG:
        import psycopg
        conn = psycopg.connect(DATABASE_URL)
    else:
        conn = sqlite3.connect(os.getenv('SQLITE_PATH', 'prices.db'))
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def run(conn, sql, params=()):
    if PG:
        sql = sql.replace('?', '%s')
    return conn.execute(sql, params)

def init():
    with connect() as c:
        run(c, '''CREATE TABLE IF NOT EXISTS products (
          id TEXT PRIMARY KEY, provider TEXT NOT NULL, name TEXT NOT NULL,
          url TEXT, unit TEXT, units_per_pack REAL, vat_status TEXT,
          active INTEGER DEFAULT 1)''')
        run(c, '''CREATE TABLE IF NOT EXISTS observations (
          id TEXT PRIMARY KEY, product_id TEXT NOT NULL,
          observed_at TEXT NOT NULL, price_clp REAL NOT NULL,
          source TEXT NOT NULL, FOREIGN KEY(product_id) REFERENCES products(id))''')
        run(c, '''CREATE TABLE IF NOT EXISTS scrape_runs (
          id TEXT PRIMARY KEY, provider TEXT NOT NULL, checked_at TEXT NOT NULL,
          status TEXT NOT NULL, products_found INTEGER, details TEXT)''')
        run(c, '''CREATE TABLE IF NOT EXISTS equivalences (
          product_a TEXT NOT NULL, product_b TEXT NOT NULL,
          confirmed INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(product_a,product_b))''')

def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')

def record_run(provider, status, count, details=''):
    import uuid
    with connect() as c:
        run(c,'INSERT INTO scrape_runs VALUES (?,?,?,?,?,?)',
            (str(uuid.uuid4()),provider,now(),status,count,details[:500]))

def save(provider, rows, source):
    import hashlib, uuid
    changed=[]
    stamp=now()
    with connect() as c:
        for item in rows:
            name=(item.get('name') or '').strip()
            url=(item.get('url') or '').strip()
            price=item.get('price')
            if not name or price is None or price<=0: continue
            key=hashlib.sha256((provider+'|'+(url or name.lower())).encode()).hexdigest()[:24]
            existing=run(c,'SELECT price_clp FROM observations WHERE product_id=? ORDER BY observed_at DESC, id DESC LIMIT 1',(key,)).fetchone()
            if PG:
                run(c,'''INSERT INTO products(id,provider,name,url,unit,units_per_pack,vat_status) VALUES(?,?,?,?,?,?,?)
                     ON CONFLICT(id) DO UPDATE SET name=EXCLUDED.name,url=EXCLUDED.url''',
                    (key,provider,name,url,item.get('unit'),item.get('units_per_pack'),item.get('vat_status')))
            else:
                run(c,'''INSERT INTO products(id,provider,name,url,unit,units_per_pack,vat_status) VALUES(?,?,?,?,?,?,?)
                     ON CONFLICT(id) DO UPDATE SET name=excluded.name,url=excluded.url''',
                    (key,provider,name,url,item.get('unit'),item.get('units_per_pack'),item.get('vat_status')))
            run(c,'INSERT INTO observations VALUES(?,?,?,?,?)',(str(uuid.uuid4()),key,stamp,float(price),source))
            if existing and float(existing[0])!=float(price):
                changed.append((provider,name,float(existing[0]),float(price),url))
    return changed
