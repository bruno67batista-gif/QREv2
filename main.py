"""Servidor web e API do QRErwk 2.0.

Desenvolvimento local: SQLite (qrerwk.sqlite3).
Produção: defina DATABASE_URL com uma URL PostgreSQL persistente.
"""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from http.cookies import SimpleCookie
import hashlib, hmac, json, os, secrets, sqlite3, time, re

ROOT = Path(__file__).parent
DB_URL = os.environ.get("DATABASE_URL", "").strip()
SQLITE_PATH = os.environ.get("DATABASE_PATH", str(ROOT / "qrerwk.sqlite3"))
COOKIE_NAME = "qrewrk_session"
SESSION_DAYS = 3650
CATALOG = {
    "ship_player": {
        "kind": "ship",
        "name": "Alpha",
        "price": 0,
        "asset": "assets/alpha.png",
    },
    "ship_player2": {
        "kind": "ship",
        "name": "Omega",
        "price": 0,
        "asset": "assets/omega.png",
    },
    "ship_azul": {
        "kind": "ship",
        "name": "MILLENIUM BIRD",
        "price": 1000,
        "asset": "assets/millenium.png",
    },
    "ship_fantasma": {
        "kind": "ship",
        "name": "Fantasma Estelar",
        "price": 2500,
        "asset": "assets/ghost.png",
    },
    "power_triple": {
        "kind": "powerup",
        "name": "Tiro triplo",
        "price": 750,
        "effect": "triple",
        "asset": "assets/triplest.png",
    },
    "power_fan": {
        "kind": "powerup",
        "name": "Leque",
        "price": 1000,
        "effect": "fan",
        "asset": "assets/lequest.png",
    },
    "power_shield": {
        "kind": "powerup",
        "name": "Escudo",
        "price": 1500,
        "effect": "shield",
        "asset": "assets/shieldpu.png",
    },
    "power_frenzy": {
        "kind": "powerup",
        "name": "Frenesi",
        "price": 2000,
        "effect": "frenzy",
        "asset": "assets/frenesipu.png",
    },
}


def connect():
    if DB_URL:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "Instale as dependências de requirements.txt para usar PostgreSQL."
            ) from exc
        conn = psycopg.connect(DB_URL, row_factory=dict_row)
        conn.autocommit = False
        return conn, True
    conn = sqlite3.connect(SQLITE_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn, False


def sql(conn, pg, statement, params=()):
    return conn.execute(statement.replace("?", "%s") if pg else statement, params)


def init_db():
    conn, pg = connect()
    try:
        if pg:
            statements = [
                "CREATE TABLE IF NOT EXISTS users (id BIGSERIAL PRIMARY KEY, nickname VARCHAR(20) UNIQUE NOT NULL, password_hash TEXT NOT NULL, coins INTEGER NOT NULL DEFAULT 0, created_at BIGINT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires_at BIGINT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS inventory (user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, item_id TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0, equipped_p1 INTEGER NOT NULL DEFAULT 0, equipped_p2 INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id,item_id))",
                "CREATE TABLE IF NOT EXISTS scores (user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, mode TEXT NOT NULL, best_score INTEGER NOT NULL DEFAULT 0, updated_at BIGINT NOT NULL, PRIMARY KEY(user_id,mode))",
            ]
        else:
            statements = [
                "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, nickname TEXT UNIQUE NOT NULL COLLATE NOCASE, password_hash TEXT NOT NULL, coins INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL)",
                "CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires_at INTEGER NOT NULL)",
                "CREATE TABLE IF NOT EXISTS inventory (user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, item_id TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0, equipped_p1 INTEGER NOT NULL DEFAULT 0, equipped_p2 INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id,item_id))",
                "CREATE TABLE IF NOT EXISTS scores (user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, mode TEXT NOT NULL, best_score INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL, PRIMARY KEY(user_id,mode))",
            ]
        for stmt in statements:
            conn.execute(stmt)
        if pg:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS users_nickname_lower_idx ON users (LOWER(nickname))"
            )
        conn.commit()
    finally:
        conn.close()


def rowdict(row):
    return dict(row) if row is not None else None


def password_hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return salt.hex() + ":" + digest.hex()


def password_ok(password, encoded):
    try:
        salt_hex, digest_hex = encoded.split(":", 1)
        actual = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1
        )
        return hmac.compare_digest(actual.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def safe_user(user):
    return {"id": user["id"], "nickname": user["nickname"], "coins": user["coins"]}


class GameHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        return

    def send_json(self, status, data, extra_headers=None):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def body(self):
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 100_000)
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return {}

    def session_token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            pass
        return cookie[COOKIE_NAME].value if COOKIE_NAME in cookie else None

    def current_user(self, conn, pg):
        token = self.session_token()
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        row = sql(
            conn,
            pg,
            "SELECT u.id,u.nickname,u.coins FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token_hash=? AND s.expires_at>?",
            (token_hash, int(time.time())),
        ).fetchone()
        return rowdict(row)

    def require_user(self, conn, pg):
        user = self.current_user(conn, pg)
        if not user:
            raise PermissionError("Faça login para continuar.")
        return user

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            try:
                conn, pg = connect()
                try:
                    if parsed.path == "/api/me":
                        user = self.current_user(conn, pg)
                        if not user:
                            return self.send_json(200, {"user": None})
                        inv = sql(
                            conn,
                            pg,
                            "SELECT item_id,active,equipped_p1,equipped_p2 FROM inventory WHERE user_id=?",
                            (user["id"],),
                        ).fetchall()
                        scores = sql(
                            conn,
                            pg,
                            "SELECT mode,best_score FROM scores WHERE user_id=?",
                            (user["id"],),
                        ).fetchall()
                        return self.send_json(
                            200,
                            {
                                "user": safe_user(user),
                                "inventory": [rowdict(r) for r in inv],
                                "scores": [rowdict(r) for r in scores],
                                "catalog": CATALOG,
                            },
                        )
                    if parsed.path == "/api/leaderboard":
                        from urllib.parse import parse_qs

                        mode = parse_qs(parsed.query).get("mode", ["singular"])[0]
                        if mode not in ("singular", "pesadelo", "dupla"):
                            return self.send_json(400, {"error": "Modo inválido."})
                        user = self.current_user(conn, pg)
                        rows = sql(
                            conn,
                            pg,
                            "SELECT u.nickname,s.best_score FROM scores s JOIN users u ON u.id=s.user_id WHERE s.mode=? ORDER BY s.best_score DESC, s.updated_at ASC LIMIT 20",
                            (mode,),
                        ).fetchall()
                        personal = (
                            sql(
                                conn,
                                pg,
                                "SELECT best_score FROM scores WHERE user_id=? AND mode=?",
                                (user["id"], mode),
                            ).fetchone()
                            if user
                            else None
                        )
                        return self.send_json(
                            200,
                            {
                                "top": [rowdict(r) for r in rows],
                                "personal_best": personal["best_score"]
                                if personal
                                else 0,
                            },
                        )
                    return self.send_json(404, {"error": "Endpoint não encontrado."})
                finally:
                    conn.close()
            except Exception as e:
                return self.send_json(
                    500,
                    {
                        "error": "Falha ao consultar os dados.",
                        "detail": str(e) if os.environ.get("DEBUG") else None,
                    },
                )
        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        super().do_GET()

    def do_POST(self):
        if not urlparse(self.path).path.startswith("/api/"):
            return self.send_json(404, {"error": "Endpoint não encontrado."})
        path = urlparse(self.path).path
        data = self.body()
        try:
            conn, pg = connect()
            headers = {}
            try:
                if path == "/api/register":
                    nickname = str(data.get("nickname", "")).strip()
                    password = str(data.get("password", ""))
                    if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", nickname):
                        return self.send_json(
                            400,
                            {
                                "error": "O nickname deve ter de 3 a 20 caracteres (letras, números ou _)."
                            },
                        )
                    if len(password) < 8 or len(password) > 128:
                        return self.send_json(
                            400, {"error": "A senha deve ter entre 8 e 128 caracteres."}
                        )
                    try:
                        cur = sql(
                            conn,
                            pg,
                            "INSERT INTO users(nickname,password_hash,coins,created_at) VALUES(?,?,0,?)",
                            (nickname, password_hash(password), int(time.time())),
                        )
                        user_id = (
                            cur.lastrowid
                            if not pg
                            else sql(
                                conn,
                                pg,
                                "SELECT id FROM users WHERE nickname=?",
                                (nickname,),
                            ).fetchone()["id"]
                        )
                        for item in ("ship_player", "ship_player2"):
                            sql(
                                conn,
                                pg,
                                "INSERT INTO inventory(user_id,item_id,active,equipped_p1,equipped_p2) VALUES(?,?,0,?,?)",
                                (
                                    user_id,
                                    item,
                                    1 if item == "ship_player" else 0,
                                    1 if item == "ship_player2" else 0,
                                ),
                            )
                        conn.commit()
                    except Exception:
                        conn.rollback()
                        return self.send_json(
                            409, {"error": "Esse nickname já está em uso."}
                        )
                    return self.create_session(conn, pg, user_id)
                if path == "/api/login":
                    nickname = str(data.get("nickname", "")).strip()
                    password = str(data.get("password", ""))
                    user = sql(
                        conn,
                        pg,
                        "SELECT id,nickname,coins,password_hash FROM users WHERE lower(nickname)=lower(?)",
                        (nickname,),
                    ).fetchone()
                    if not user or not password_ok(password, user["password_hash"]):
                        return self.send_json(
                            401, {"error": "Nickname ou senha incorretos."}
                        )
                    return self.create_session(conn, pg, user["id"])
                if path == "/api/logout":
                    token = self.session_token()
                    if token:
                        sql(
                            conn,
                            pg,
                            "DELETE FROM sessions WHERE token_hash=?",
                            (hashlib.sha256(token.encode()).hexdigest(),),
                        )
                        conn.commit()
                    headers["Set-Cookie"] = (
                        f"{COOKIE_NAME}=; HttpOnly; Path=/; SameSite=Lax; Max-Age=0"
                    )
                    return self.send_json(200, {"ok": True}, headers)
                if path == "/api/delete-account":
                    user = self.require_user(conn, pg)
                    password = str(data.get("password", ""))
                    row = sql(
                        conn,
                        pg,
                        "SELECT password_hash FROM users WHERE id=?",
                        (user["id"],),
                    ).fetchone()
                    if not row or not password_ok(password, row["password_hash"]):
                        return self.send_json(403, {"error": "Senha incorreta."})
                    sql(conn, pg, "DELETE FROM users WHERE id=?", (user["id"],))
                    conn.commit()
                    headers["Set-Cookie"] = (
                        f"{COOKIE_NAME}=; HttpOnly; Path=/; SameSite=Lax; Max-Age=0"
                    )
                    return self.send_json(200, {"ok": True}, headers)
                user = self.require_user(conn, pg)
                if path == "/api/purchase":
                    item_id = str(data.get("item_id", ""))
                    item = CATALOG.get(item_id)
                    if not item:
                        return self.send_json(400, {"error": "Item inválido."})
                    if sql(
                        conn,
                        pg,
                        "SELECT 1 FROM inventory WHERE user_id=? AND item_id=?",
                        (user["id"], item_id),
                    ).fetchone():
                        return self.send_json(
                            409, {"error": "Você já possui esse item."}
                        )
                    fresh = sql(
                        conn, pg, "SELECT coins FROM users WHERE id=?", (user["id"],)
                    ).fetchone()
                    coins = fresh["coins"]
                    if coins < item["price"]:
                        return self.send_json(400, {"error": "Moedas insuficientes."})
                    sql(
                        conn,
                        pg,
                        "UPDATE users SET coins=coins-? WHERE id=?",
                        (item["price"], user["id"]),
                    )
                    sql(
                        conn,
                        pg,
                        "INSERT INTO inventory(user_id,item_id,active,equipped_p1,equipped_p2) VALUES(?,?,0,0,0)",
                        (user["id"], item_id),
                    )
                    conn.commit()
                    return self.send_json(
                        200, {"ok": True, "coins": coins - item["price"]}
                    )
                if path == "/api/toggle-powerup":
                    item_id = str(data.get("item_id", ""))
                    active = bool(data.get("active"))
                    item = CATALOG.get(item_id)
                    if not item or item["kind"] != "powerup":
                        return self.send_json(400, {"error": "Power-up inválido."})
                    cur = sql(
                        conn,
                        pg,
                        "UPDATE inventory SET active=? WHERE user_id=? AND item_id=?",
                        (1 if active else 0, user["id"], item_id),
                    )
                    if cur.rowcount == 0:
                        return self.send_json(
                            404, {"error": "Você não possui esse power-up."}
                        )
                    conn.commit()
                    return self.send_json(200, {"ok": True})
                if path == "/api/equip-ship":
                    item_id = str(data.get("item_id", ""))
                    slot = str(data.get("slot", "p1"))
                    item = CATALOG.get(item_id)
                    if not item or item["kind"] != "ship" or slot not in ("p1", "p2"):
                        return self.send_json(
                            400, {"error": "Nave ou jogador inválido."}
                        )
                    if not sql(
                        conn,
                        pg,
                        "SELECT 1 FROM inventory WHERE user_id=? AND item_id=?",
                        (user["id"], item_id),
                    ).fetchone():
                        return self.send_json(
                            403, {"error": "Você não possui essa nave."}
                        )
                    col = "equipped_p1" if slot == "p1" else "equipped_p2"
                    sql(
                        conn,
                        pg,
                        f"UPDATE inventory SET {col}=0 WHERE user_id=?",
                        (user["id"],),
                    )
                    sql(
                        conn,
                        pg,
                        f"UPDATE inventory SET {col}=1 WHERE user_id=? AND item_id=?",
                        (user["id"], item_id),
                    )
                    conn.commit()
                    return self.send_json(200, {"ok": True})
                if path == "/api/finish-run":
                    mode = str(data.get("mode", ""))
                    score = max(0, min(2_000_000_000, int(data.get("score", 0))))
                    coins = max(0, min(1_000_000, int(data.get("coins", 0))))
                    if mode not in ("singular", "pesadelo", "dupla"):
                        return self.send_json(400, {"error": "Modo inválido."})
                    # Recompensas são calculadas durante a partida no cliente; o endpoint limita valores, mas produção deve migrar a simulação/recompensa para validação server-side.
                    sql(
                        conn,
                        pg,
                        "UPDATE users SET coins=coins+? WHERE id=?",
                        (coins, user["id"]),
                    )
                    old = sql(
                        conn,
                        pg,
                        "SELECT best_score FROM scores WHERE user_id=? AND mode=?",
                        (user["id"], mode),
                    ).fetchone()
                    if old:
                        if score > old["best_score"]:
                            sql(
                                conn,
                                pg,
                                "UPDATE scores SET best_score=?,updated_at=? WHERE user_id=? AND mode=?",
                                (score, int(time.time()), user["id"], mode),
                            )
                    else:
                        sql(
                            conn,
                            pg,
                            "INSERT INTO scores(user_id,mode,best_score,updated_at) VALUES(?,?,?,?)",
                            (user["id"], mode, score, int(time.time())),
                        )
                    conn.commit()
                    return self.send_json(
                        200,
                        {
                            "ok": True,
                            "coins": sql(
                                conn,
                                pg,
                                "SELECT coins FROM users WHERE id=?",
                                (user["id"],),
                            ).fetchone()["coins"],
                        },
                    )
                return self.send_json(404, {"error": "Endpoint não encontrado."})
            finally:
                conn.close()
        except PermissionError as e:
            return self.send_json(401, {"error": str(e)})
        except Exception as e:
            return self.send_json(
                500,
                {
                    "error": "Erro interno no servidor.",
                    "detail": str(e) if os.environ.get("DEBUG") else None,
                },
            )

    def create_session(self, conn, pg, user_id):
        token = secrets.token_urlsafe(32)
        expiry = int(time.time()) + SESSION_DAYS * 86400
        sql(
            conn,
            pg,
            "INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)",
            (hashlib.sha256(token.encode()).hexdigest(), user_id, expiry),
        )
        conn.commit()
        user = sql(
            conn, pg, "SELECT id,nickname,coins FROM users WHERE id=?", (user_id,)
        ).fetchone()
        header = f"{COOKIE_NAME}={token}; HttpOnly; Path=/; SameSite=Lax; Max-Age={SESSION_DAYS * 86400}"
        if (
            os.environ.get("COOKIE_SECURE", "").lower() in ("1", "true", "yes")
            or self.headers.get("X-Forwarded-Proto") == "https"
        ):
            header += "; Secure"
        return self.send_json(
            200, {"ok": True, "user": safe_user(user)}, {"Set-Cookie": header}
        )


init_db()
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), GameHandler)
    print(
        f"QRErwk 2.0 server on port {port}; database={'PostgreSQL' if DB_URL else 'SQLite local'}"
    )
    server.serve_forever()
