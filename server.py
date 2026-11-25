import hashlib
import hmac
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Literal, TypedDict

import pymysql
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from database import connect_database
from driver_panel import create_driver_router


BASE_DIR = Path(__file__).resolve().parent
SESSION_COOKIE = "veloz_session"
SESSION_MAX_AGE = 7 * 24 * 60 * 60
SECURE_COOKIE = os.environ.get("VELOZ_ENV", "development").lower() == "production"
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ALLOWED_ASSETS = {
    "style.css",
    "script.js",
    "driver-dashboard.css",
    "driver-dashboard.js",
    "moto.png.png",
    "icon.jpg",
}

app = FastAPI(title="Veloz", docs_url=None, redoc_url=None, openapi_url=None)


class User(TypedDict):
    name: str
    email: str
    account_type: Literal["cliente", "mototaxista", "admin"]
    age: int | None
    phone: str
    password_hash: str
    cpf: str | None
    cnh: str | None
    cnh_category: str | None
    cnh_expiry: str | None
    motorcycle: str | None
    plate: str | None


class Session(TypedDict):
    user: User
    expires_at: int


class RegisterRequest(BaseModel):
    accountType: Literal["cliente", "mototaxista"]
    name: str = Field(min_length=2, max_length=120)
    age: int = Field(ge=18, le=100)
    email: str = Field(min_length=5, max_length=254)
    phone: str = Field(min_length=8, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    cpf: str | None = None
    cnh: str | None = None
    cnhCategory: str | None = None
    cnhExpiry: str | None = None
    motorcycle: str | None = None
    plate: str | None = None


class LoginRequest(BaseModel):
    accountType: Literal["cliente", "mototaxista", "admin"]
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=128)


_sessions: dict[str, Session] = {}
_store_lock = threading.RLock()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=64,
    )
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    try:
        algorithm, salt_hex, digest_hex = stored_hash.split("$", 2)
        if algorithm != "scrypt":
            return False
        expected_digest = bytes.fromhex(digest_hex)
        actual_digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=2**14,
            r=8,
            p=1,
            dklen=len(expected_digest),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual_digest, expected_digest)


def normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if not EMAIL_PATTERN.fullmatch(normalized):
        raise HTTPException(status_code=422, detail="Informe um e-mail válido.")
    return normalized


def validate_driver_details(payload: RegisterRequest) -> dict[str, str] | None:
    if payload.accountType != "mototaxista":
        return None

    cpf = re.sub(r"\D", "", payload.cpf or "")
    cnh = re.sub(r"\D", "", payload.cnh or "")
    category = (payload.cnhCategory or "").strip().upper()
    expiry = (payload.cnhExpiry or "").strip()
    motorcycle = (payload.motorcycle or "").strip()
    plate = (payload.plate or "").strip().upper()

    if len(cpf) != 11:
        raise HTTPException(status_code=422, detail="Informe um CPF com 11 dígitos.")
    if len(cnh) != 11:
        raise HTTPException(status_code=422, detail="Informe uma CNH com 11 dígitos.")
    if category not in {"A", "B", "A/B"}:
        raise HTTPException(status_code=422, detail="Selecione uma categoria de CNH válida.")
    try:
        expiry_date = date.fromisoformat(expiry)
    except ValueError:
        raise HTTPException(status_code=422, detail="Informe a validade da CNH.") from None
    if expiry_date < date.today():
        raise HTTPException(status_code=422, detail="A CNH informada está vencida.")
    if not motorcycle:
        raise HTTPException(status_code=422, detail="Informe o modelo da moto.")
    if not re.fullmatch(r"[A-Z]{3}\d[A-Z0-9]\d{2}|[A-Z]{3}\d{4}", plate):
        raise HTTPException(status_code=422, detail="Informe uma placa válida.")

    return {
        "cpf": cpf,
        "cnh": cnh,
        "cnh_category": category,
        "cnh_expiry": expiry,
        "motorcycle": motorcycle,
        "plate": plate,
    }


def public_user(user: User) -> dict[str, str]:
    return {
        "name": user["name"],
        "email": user["email"],
        "accountType": user["account_type"],
        "phone": user["phone"],
    }


def session_user(request: Request) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with _store_lock:
        session = _sessions.get(token_hash)
        if session is None:
            return None
        if session["expires_at"] <= int(time.time()):
            del _sessions[token_hash]
            return None
        return session["user"]


def connect_auth_database():
    backend = os.environ.get("VELOZ_DATABASE_BACKEND")
    if backend == "sqlite":
        return connect_database("sqlite")
    try:
        return connect_database("mysql")
    except Exception as exc:
        if backend == "mysql":
            raise
        logging.warning("MySQL indisponível (%s). Usando fallback SQLite.", exc)
        return connect_database("sqlite")


def _sync_user_to_sqlite(
    account_type: str,
    name: str,
    email: str,
    phone: str,
    age: int | None,
    password_hash: str | None,
    driver: dict[str, Any] | None = None,
) -> None:
    try:
        sqlite_conn = connect_database("sqlite")
        try:
            with closing(sqlite_conn.cursor()) as cur:
                if account_type == "mototaxista" and driver:
                    cur.execute(
                        """
                        INSERT INTO `mototaxistas`
                            (`nome`, `email`, `telefone`, `idade`, `senha_hash`, `cpf`,
                             `cnh`, `categoria_cnh`, `validade_cnh`, `moto`, `placa`)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(email) DO UPDATE SET
                            nome = excluded.nome,
                            telefone = excluded.telefone,
                            idade = excluded.idade,
                            senha_hash = excluded.senha_hash,
                            cpf = excluded.cpf,
                            cnh = excluded.cnh,
                            categoria_cnh = excluded.categoria_cnh,
                            validade_cnh = excluded.validade_cnh,
                            moto = excluded.moto,
                            placa = excluded.placa
                        """,
                        (
                            name,
                            email,
                            phone,
                            age,
                            password_hash,
                            driver.get("cpf"),
                            driver.get("cnh"),
                            driver.get("cnh_category"),
                            driver.get("cnh_expiry"),
                            driver.get("motorcycle"),
                            driver.get("plate"),
                        ),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO `usuarios`
                            (`nome`, `email`, `telefone`, `idade`, `senha_hash`)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(email) DO UPDATE SET
                            nome = excluded.nome,
                            telefone = excluded.telefone,
                            idade = excluded.idade,
                            senha_hash = excluded.senha_hash
                        """,
                        (name, email, phone, age, password_hash),
                    )
            sqlite_conn.commit()
        finally:
            sqlite_conn.close()
    except Exception:
        logging.warning("Não foi possível espelhar usuário no SQLite local.")


@app.post("/api/register", status_code=201)
def register(payload: RegisterRequest) -> dict[str, str]:
    email = normalize_email(payload.email)
    name = payload.name.strip()
    phone = payload.phone.strip()
    if len(name) < 2:
        raise HTTPException(status_code=422, detail="Informe seu nome completo.")
    if len(phone) < 8:
        raise HTTPException(status_code=422, detail="Informe um celular válido.")

    driver = validate_driver_details(payload) or {}

    password_hash = hash_password(payload.password)
    connection = None
    is_sqlite = False
    try:
        connection = connect_auth_database()
        is_sqlite = isinstance(connection, sqlite3.Connection)
        placeholder = "?" if is_sqlite else "%s"
        with closing(connection.cursor()) as cursor:
            if driver:
                cursor.execute(
                    """
                    INSERT INTO `mototaxistas`
                        (`nome`, `email`, `telefone`, `idade`, `senha_hash`, `cpf`,
                         `cnh`, `categoria_cnh`, `validade_cnh`, `moto`, `placa`)
                    VALUES ({})
                    """.format(", ".join([placeholder] * 11)),
                    (
                        name,
                        email,
                        phone,
                        payload.age,
                        password_hash,
                        driver["cpf"],
                        driver["cnh"],
                        driver["cnh_category"],
                        driver["cnh_expiry"],
                        driver["motorcycle"],
                        driver["plate"],
                    ),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO `usuarios`
                        (`nome`, `email`, `telefone`, `idade`, `senha_hash`)
                    VALUES ({})
                    """.format(", ".join([placeholder] * 5)),
                    (name, email, phone, payload.age, password_hash),
                )
        connection.commit()
    except (sqlite3.IntegrityError, pymysql.err.IntegrityError) as exc:
        if connection is not None:
            connection.rollback()
        raise HTTPException(
            status_code=409,
            detail="Já existe um cadastro com este e-mail para esse tipo de conta.",
        ) from exc
    except (sqlite3.Error, pymysql.MySQLError) as exc:
        if connection is not None:
            connection.rollback()
        logging.exception("Falha ao salvar cadastro no banco de dados.")
        raise HTTPException(
            status_code=503,
            detail="Não foi possível acessar o banco de dados configurado.",
        ) from exc
    finally:
        if connection is not None:
            connection.close()

    if not is_sqlite:
        _sync_user_to_sqlite(
            account_type=payload.accountType,
            name=name,
            email=email,
            phone=phone,
            age=payload.age,
            password_hash=password_hash,
            driver=driver if payload.accountType == "mototaxista" else None,
        )

    return {"name": name, "email": email, "accountType": payload.accountType}


@app.post("/api/login")
def login(payload: LoginRequest, response: Response) -> dict[str, dict[str, str]]:
    email = normalize_email(payload.email)
    if payload.accountType == "admin":
        admin_email = os.environ.get("VELOZ_ADMIN_EMAIL", "").strip().lower()
        admin_password = os.environ.get("VELOZ_ADMIN_PASSWORD", "")
        if (
            not EMAIL_PATTERN.fullmatch(admin_email)
            or len(admin_password) < 16
        ):
            raise HTTPException(
                status_code=503,
                detail=(
                    "Configure VELOZ_ADMIN_EMAIL e uma VELOZ_ADMIN_PASSWORD "
                    "com pelo menos 16 caracteres."
                ),
            )
        if not hmac.compare_digest(email, admin_email) or not hmac.compare_digest(
            payload.password,
            admin_password,
        ):
            raise HTTPException(status_code=401, detail="E-mail ou senha inválidos.")

        user: User = {
            "name": "Administrador",
            "email": admin_email,
            "account_type": "admin",
            "age": None,
            "phone": "",
            "password_hash": "",
            "cpf": None,
            "cnh": None,
            "cnh_category": None,
            "cnh_expiry": None,
            "motorcycle": None,
            "plate": None,
        }
    else:
        table = "mototaxistas" if payload.accountType == "mototaxista" else "usuarios"
        columns = (
            "`nome` AS `name`, `email`, `telefone` AS `phone`, `idade` AS `age`, "
            "`senha_hash` AS `password_hash`, `cpf`, `cnh`, "
            "`categoria_cnh` AS `cnh_category`, `validade_cnh` AS `cnh_expiry`, "
            "`moto` AS `motorcycle`, `placa` AS `plate`"
            if payload.accountType == "mototaxista"
            else "`nome` AS `name`, `email`, `telefone` AS `phone`, `idade` AS `age`, "
            "`senha_hash` AS `password_hash`"
        )
        connection = None
        is_sqlite = False
        try:
            connection = connect_auth_database()
            is_sqlite = isinstance(connection, sqlite3.Connection)
            placeholder = "?" if is_sqlite else "%s"
            with closing(connection.cursor()) as cursor:
                cursor.execute(
                    "SELECT {} FROM `{}` WHERE `email` = {} LIMIT 1".format(
                        columns,
                        table,
                        placeholder,
                    ),
                    (email,),
                )
                row = cursor.fetchone()
            if row is None or not verify_password(payload.password, row["password_hash"]):
                raise HTTPException(status_code=401, detail="E-mail ou senha inválidos.")

            expiry = row.get("cnh_expiry")
            user: User = {
                "name": row["name"],
                "email": row["email"],
                "account_type": payload.accountType,
                "age": row["age"],
                "phone": row["phone"],
                "password_hash": row["password_hash"],
                "cpf": row.get("cpf"),
                "cnh": row.get("cnh"),
                "cnh_category": row.get("cnh_category"),
                "cnh_expiry": (
                    expiry.isoformat() if isinstance(expiry, date) else expiry
                ),
                "motorcycle": row.get("motorcycle"),
                "plate": row.get("plate"),
            }
        except HTTPException:
            raise
        except (sqlite3.Error, pymysql.MySQLError) as exc:
            logging.exception("Falha ao consultar cadastro no banco de dados.")
            raise HTTPException(
                status_code=503,
                detail="Não foi possível acessar o banco de dados configurado.",
            ) from exc
        finally:
            if connection is not None:
                connection.close()

        if not is_sqlite:
            _sync_user_to_sqlite(
                account_type=payload.accountType,
                name=user["name"],
                email=user["email"],
                phone=user["phone"],
                age=user["age"],
                password_hash=user["password_hash"],
                driver={
                    "cpf": user.get("cpf"),
                    "cnh": user.get("cnh"),
                    "cnh_category": user.get("cnh_category"),
                    "cnh_expiry": user.get("cnh_expiry"),
                    "motorcycle": user.get("motorcycle"),
                    "plate": user.get("plate"),
                } if payload.accountType == "mototaxista" else None,
            )

    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = int(time.time()) + SESSION_MAX_AGE
    with _store_lock:
        expired_sessions = [
            session_hash
            for session_hash, session in _sessions.items()
            if session["expires_at"] <= int(time.time())
        ]
        for session_hash in expired_sessions:
            del _sessions[session_hash]
        _sessions[token_hash] = {"user": user, "expires_at": expires_at}

    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=SECURE_COOKIE,
        samesite="lax",
        path="/",
    )
    return {"user": public_user(user)}


@app.get("/api/me")
def current_user(request: Request) -> dict[str, dict[str, str] | None]:
    user = session_user(request)
    return {"user": public_user(user) if user is not None else None}


@app.post("/api/logout")
def logout(request: Request, response: Response) -> dict[str, bool]:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with _store_lock:
            _sessions.pop(token_hash, None)
    response.delete_cookie(
        key=SESSION_COOKIE,
        secure=SECURE_COOKIE,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return {"ok": True}


@app.get("/")
def home_page() -> FileResponse:
    return FileResponse(BASE_DIR / "index.html")


@app.get("/login")
def login_page(request: Request) -> Response:
    user = session_user(request)
    if user is not None:
        destination = {
            "mototaxista": "/painel",
            "admin": "/inicio",
        }.get(user["account_type"], "/inicio")
        return RedirectResponse(destination, status_code=303)
    query_str = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(f"/{query_str}#login", status_code=303)


@app.get("/cadastro")
def registration_page(request: Request) -> Response:
    user = session_user(request)
    if user is not None:
        destination = {
            "mototaxista": "/painel",
            "admin": "/inicio",
        }.get(user["account_type"], "/inicio")
        return RedirectResponse(destination, status_code=303)
    query_str = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(f"/{query_str}#cadastro", status_code=303)


@app.get("/painel")
def driver_panel_page(request: Request) -> Response:
    user = session_user(request)
    if user is None:
        return RedirectResponse("/login?tipo=mototaxista", status_code=303)
    if user["account_type"] != "mototaxista":
        return RedirectResponse("/inicio", status_code=303)
    return FileResponse(BASE_DIR / "driver-dashboard.html")


@app.get("/inicio")
def landing_page() -> FileResponse:
    return FileResponse(BASE_DIR / "index.html")


@app.get("/entrega")
def delivery_page(request: Request) -> Response:
    return RedirectResponse("/#enviar-pedido", status_code=303)


@app.get("/admin-entregas")
def delivery_admin_page(request: Request) -> Response:
    return RedirectResponse("/inicio", status_code=303)


@app.get("/{asset_name}")
def asset(asset_name: str) -> FileResponse:
    if asset_name not in ALLOWED_ASSETS:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    return FileResponse(BASE_DIR / asset_name)


app.include_router(create_driver_router(session_user, lambda: connect_database("sqlite")))
