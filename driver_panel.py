import csv
import hashlib
import io
import json
import logging
import math
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
import pymysql


RideStatus = Literal["solicitada", "aceita", "em_andamento", "concluida", "cancelada"]
ExpenseCategory = Literal[
    "Combustível",
    "Manutenção",
    "Troca de óleo",
    "Pneus",
    "Estacionamento",
    "Outras despesas",
]
ReportKind = Literal[
    "resumo",
    "corridas",
    "financeiro",
    "despesas",
    "desempenho",
    "distancia",
    "rotas",
]
BASE_FARE_CENTS = 700
# Limite municipal simplificado da malha do IBGE (Serra Talhada, código 2613909).
_SERRA_TALHADA_BOUNDARY = (
    (-38.0282, -8.1336),
    (-38.0974, -8.0541),
    (-38.1494, -7.9454),
    (-38.1635, -7.9054),
    (-38.2383, -7.9061),
    (-38.2067, -7.8382),
    (-38.2219, -7.8204),
    (-38.2755, -7.8342),
    (-38.2934, -7.823),
    (-38.2957, -7.7752),
    (-38.3109, -7.7391),
    (-38.3267, -7.6937),
    (-38.355, -7.6784),
    (-38.4095, -7.7305),
    (-38.4342, -7.7205),
    (-38.4571, -7.7181),
    (-38.4966, -7.75),
    (-38.5936, -7.7543),
    (-38.6235, -7.7868),
    (-38.6276, -7.822),
    (-38.5553, -7.9053),
    (-38.558, -7.94),
    (-38.6079, -8.0373),
    (-38.6205, -8.0988),
    (-38.5983, -8.1323),
    (-38.5893, -8.1281),
    (-38.5366, -8.2309),
    (-38.5558, -8.2657),
    (-38.5495, -8.2883),
    (-38.4995, -8.3202),
    (-38.5174, -8.4005),
    (-38.515, -8.4385),
    (-38.469, -8.402),
    (-38.4499, -8.3671),
    (-38.4175, -8.3415),
    (-38.4066, -8.3058),
    (-38.3677, -8.2808),
    (-38.3143, -8.2917),
    (-38.2908, -8.2851),
    (-38.2648, -8.2539),
    (-38.2067, -8.2854),
    (-38.1787, -8.2767),
    (-38.1524, -8.2234),
    (-38.1188, -8.2211),
    (-38.1066, -8.1867),
    (-38.0627, -8.1481),
    (-38.0282, -8.1336),
)


def _is_within_serra_talhada(latitude: float, longitude: float) -> bool:
    if not math.isfinite(latitude) or not math.isfinite(longitude):
        return False
    if not (-8.4385 <= latitude <= -7.6784 and -38.6276 <= longitude <= -38.0282):
        return False

    inside = False
    previous_longitude, previous_latitude = _SERRA_TALHADA_BOUNDARY[-1]
    for current_longitude, current_latitude in _SERRA_TALHADA_BOUNDARY:
        crosses_latitude = (current_latitude > latitude) != (previous_latitude > latitude)
        if crosses_latitude:
            intersection_longitude = (
                (previous_longitude - current_longitude)
                * (latitude - current_latitude)
                / (previous_latitude - current_latitude)
                + current_longitude
            )
            if longitude < intersection_longitude:
                inside = not inside
        previous_longitude, previous_latitude = current_longitude, current_latitude
    return inside


class RideRequest(BaseModel):
    pickup: str = Field(min_length=3, max_length=255)
    destination: str = Field(min_length=3, max_length=255)
    pickup_lat: float = Field(ge=-90, le=90)
    pickup_lng: float = Field(ge=-180, le=180)
    destination_lat: float = Field(ge=-90, le=90)
    destination_lng: float = Field(ge=-180, le=180)
    passenger_name: str | None = Field(default=None, max_length=120)
    passenger_phone: str | None = Field(default=None, max_length=32)
    scheduled_at: datetime | None = None
    is_immediate: bool = False
    for_another_person: bool = False
    payment_method: Literal["Dinheiro"]
    idempotency_key: UUID
    service_type: Literal["passageiro", "pedido"] = "passageiro"


class CustomerProfileRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=32)


class RideStatusRequest(BaseModel):
    status: Literal["em_andamento", "concluida", "cancelada"]


class AvailabilityRequest(BaseModel):
    online: bool


class ExpenseRequest(BaseModel):
    category: ExpenseCategory
    description: str = Field(min_length=2, max_length=240)
    amount_cents: int = Field(gt=0, le=100_000_000)
    spent_on: date


class GoalRequest(BaseModel):
    period: Literal["diaria", "semanal", "mensal"]
    target_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    target_rides: int | None = Field(default=None, ge=0, le=100_000)


class GpsPointRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_m: float = Field(ge=0, le=100)
    recorded_at: datetime | None = None


class ReviewRequest(BaseModel):
    stars: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


class ProfileRequest(BaseModel):
    phone: str = Field(min_length=8, max_length=32)
    motorcycle: str = Field(min_length=2, max_length=120)
    plate: str = Field(min_length=7, max_length=8)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(value: datetime | None = None) -> str:
    current = value or _now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    precision = "microseconds" if current.microsecond else "seconds"
    return current.isoformat(timespec=precision)


def _date_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _period_bounds(
    period: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[datetime, datetime, int]:
    today = _now().date()
    if start_date is not None or end_date is not None:
        start = start_date or (today - timedelta(days=29))
        end = end_date or today
        if end < start:
            raise HTTPException(status_code=422, detail="A data final deve ser posterior à data inicial.")
        if (end - start).days > 365:
            raise HTTPException(status_code=422, detail="O período máximo permitido é de 366 dias.")
        return _date_start(start), _date_start(end + timedelta(days=1)), (end - start).days + 1

    days = {"hoje": 1, "7dias": 7, "30dias": 30}[period]
    return (
        _date_start(today - timedelta(days=days - 1)),
        _utc_iso_datetime(_now()),
        days,
    )


def _utc_iso_datetime(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def _record(row: Any) -> dict[str, Any]:
    return dict(row) if row is not None else {}


def _ride_payload(row: Any) -> dict[str, Any]:
    ride = _record(row)
    ride["service_type"] = ride.pop("tipo_servico", "passageiro") or "passageiro"
    ride["amount_cents"] = ride.pop("valor_centavos", 0)
    ride["payment_method"] = ride.pop("forma_pagamento", "")
    ride["payment_status"] = ride.pop("pagamento_status", "")
    ride["created_at"] = ride.pop("criada_em", "")
    ride["scheduled_at"] = ride.pop("agendada_para", "")
    ride["pickup"] = ride.pop("embarque", "")
    ride["destination"] = ride.pop("destino", "")
    ride["gps_distance_m"] = ride.pop("distancia_gps_m", 0)
    ride["duration_seconds"] = ride.pop("duracao_segundos", None)
    ride["completed_at"] = ride.pop("finalizada_em", None)
    ride["status"] = ride.pop("status", "")
    return ride


def _distance_meters(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    earth_radius_m = 6_371_000
    lat_a, lat_b = math.radians(latitude_a), math.radians(latitude_b)
    delta_lat = math.radians(latitude_b - latitude_a)
    delta_lon = math.radians(longitude_b - longitude_a)
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
    )
    haversine = min(1.0, max(0.0, haversine))
    return earth_radius_m * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))


def _online_seconds(
    connection: sqlite3.Connection,
    driver_email: str,
    start: datetime,
    end: datetime,
) -> int:
    start_iso, end_iso = _utc_iso(start), _utc_iso(end)
    previous = connection.execute(
        """
        SELECT online FROM eventos_disponibilidade
        WHERE mototaxista_email = ? AND registrada_em < ?
        ORDER BY registrada_em DESC, id DESC LIMIT 1
        """,
        (driver_email, start_iso),
    ).fetchone()
    state = bool(previous["online"]) if previous else False
    cursor_time = start
    seconds = 0
    events = connection.execute(
        """
        SELECT online, registrada_em FROM eventos_disponibilidade
        WHERE mototaxista_email = ? AND registrada_em >= ? AND registrada_em < ?
        ORDER BY registrada_em, id
        """,
        (driver_email, start_iso, end_iso),
    ).fetchall()
    for event in events:
        event_time = datetime.fromisoformat(event["registrada_em"])
        if state:
            seconds += max(0, int((event_time - cursor_time).total_seconds()))
        cursor_time = event_time
        state = bool(event["online"])
    if state:
        seconds += max(0, int((end - cursor_time).total_seconds()))
    return seconds


def _notify(
    connection: sqlite3.Connection,
    driver_email: str,
    kind: str,
    title: str,
    message: str,
) -> None:
    connection.execute(
        """
        INSERT INTO notificacoes_mototaxista
            (mototaxista_email, tipo, titulo, mensagem, criada_em)
        VALUES (?, ?, ?, ?, ?)
        """,
        (driver_email, kind, title, message, _utc_iso()),
    )


def _availability_online(connection: sqlite3.Connection, driver_email: str) -> bool:
    row = connection.execute(
        """
        SELECT online, alterada_em, last_seen_em FROM disponibilidade_mototaxista
        WHERE mototaxista_email = ?
        """,
        (driver_email,),
    ).fetchone()
    if not row or not row["online"]:
        return False
    last_seen = row["last_seen_em"] or row["alterada_em"]
    expires_at = datetime.fromisoformat(last_seen) + timedelta(minutes=2)
    if _now() > expires_at:
        expiry_iso = _utc_iso(expires_at)
        connection.execute(
            """
            UPDATE disponibilidade_mototaxista
            SET online = 0, alterada_em = ? WHERE mototaxista_email = ?
            """,
            (expiry_iso, driver_email),
        )
        connection.execute(
            """
            INSERT INTO eventos_disponibilidade
                (mototaxista_email, online, registrada_em)
            VALUES (?, 0, ?)
            """,
            (driver_email, expiry_iso),
        )
        return False
    connection.execute(
        "UPDATE disponibilidade_mototaxista SET last_seen_em = ? WHERE mototaxista_email = ?",
        (_utc_iso(), driver_email),
    )
    return True


def _expire_stale_drivers(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT mototaxista_email FROM disponibilidade_mototaxista
        WHERE online = 1
        """
    ).fetchall()
    for row in rows:
        _availability_online(connection, row["mototaxista_email"])


def create_driver_router(
    session_lookup: Callable[[Request], dict[str, Any] | None],
    database_connector: Callable[[], Any],
) -> APIRouter:
    router = APIRouter()

    def require_driver(request: Request) -> dict[str, Any]:
        user = session_lookup(request)
        if user is None:
            raise HTTPException(status_code=401, detail="Entre na sua conta para continuar.")
        if user["account_type"] != "mototaxista":
            raise HTTPException(status_code=403, detail="Este recurso é exclusivo para mototaxistas.")
        return user

    def require_customer(request: Request) -> dict[str, Any]:
        user = session_lookup(request)
        if user is None:
            raise HTTPException(status_code=401, detail="Entre na sua conta para continuar.")
        if user["account_type"] != "cliente":
            raise HTTPException(status_code=403, detail="A solicitação de corrida é exclusiva para clientes.")
        return user

    @contextmanager
    def database_session():
        try:
            connection = database_connector()
        except (sqlite3.Error, pymysql.MySQLError, OSError, ValueError) as exc:
            logging.exception("Não foi possível abrir o banco SQLite do painel.")
            raise HTTPException(status_code=503, detail="Banco de dados indisponível.") from exc
        if not isinstance(connection, sqlite3.Connection):
            connection.close()
            raise HTTPException(
                status_code=503,
                detail="O painel está habilitado para SQLite nesta etapa; a migração MySQL não foi executada.",
            )
        try:
            yield connection
            connection.commit()
        except sqlite3.Error as exc:
            connection.rollback()
            logging.exception("Falha na operação SQLite do painel.")
            raise HTTPException(status_code=503, detail="Não foi possível concluir a operação no banco de dados.") from exc
        finally:
            connection.close()

    @router.put("/api/customer/profile")
    def update_customer_profile(
        payload: CustomerProfileRequest,
        customer: dict[str, Any] = Depends(require_customer),
    ) -> dict[str, str]:
        assignments: list[str] = []
        values: list[str] = []
        updated_fields: dict[str, str] = {}
        if payload.name is not None:
            name = " ".join(payload.name.split())
            if len(name) < 2:
                raise HTTPException(status_code=422, detail="Informe seu nome completo.")
            assignments.append('"nome" = ?')
            values.append(name)
            updated_fields["name"] = name
        if payload.phone is not None:
            phone = re.sub(r"\D", "", payload.phone)
            if len(phone) != 11:
                raise HTTPException(
                    status_code=422,
                    detail="Informe um celular brasileiro com DDD e 11 dígitos.",
                )
            assignments.append('"telefone" = ?')
            values.append(phone)
            updated_fields["phone"] = phone
        if not assignments:
            raise HTTPException(status_code=422, detail="Informe ao menos um dado para atualizar.")

        with database_session() as connection:
            cursor = connection.execute(
                f'UPDATE usuarios SET {", ".join(assignments)} WHERE email = ?',
                [*values, customer["email"]],
            )
            if cursor.rowcount != 1:
                raise HTTPException(status_code=404, detail="Cadastro de cliente não encontrado.")

        try:
            mysql_conn = pymysql.connect(
                host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
                port=int(os.environ.get("MYSQL_PORT", "3306")),
                user=os.environ.get("MYSQL_USER", "root"),
                password=os.environ.get("MYSQL_PASSWORD", ""),
                database=os.environ.get("MYSQL_DATABASE", "mototaxi"),
                charset="utf8mb4",
                autocommit=True,
            )
            with mysql_conn.cursor() as mcur:
                mysql_assignments = [a.replace('"', '`').replace('?', '%s') for a in assignments]
                mcur.execute(
                    f"UPDATE `usuarios` SET {', '.join(mysql_assignments)} WHERE `email` = %s",
                    [*values, customer["email"]],
                )
            mysql_conn.close()
        except Exception:
            pass
        customer.update(updated_fields)
        return {
            "name": customer["name"],
            "phone": customer["phone"],
        }

    def dashboard_data(
        connection: sqlite3.Connection,
        driver_email: str,
        start: datetime,
        end: datetime,
        chart_days: int,
    ) -> dict[str, Any]:
        start_iso, end_iso = _utc_iso(start), _utc_iso(end)
        rides = connection.execute(
            """
            SELECT
                COUNT(*) AS requested,
                SUM(CASE WHEN status = 'concluida' THEN 1 ELSE 0 END) AS completed,
                SUM(CASE WHEN status = 'cancelada' THEN 1 ELSE 0 END) AS cancelled,
                SUM(CASE WHEN status = 'em_andamento' THEN 1 ELSE 0 END) AS in_progress,
                SUM(CASE WHEN status = 'concluida' AND pagamento_status = 'confirmado'
                    THEN valor_centavos ELSE 0 END) AS paid_cents,
                SUM(CASE WHEN status = 'concluida' AND pagamento_status = 'pendente'
                    THEN valor_centavos ELSE 0 END) AS pending_cents,
                SUM(CASE WHEN status = 'concluida' THEN distancia_gps_m ELSE 0 END) AS gps_distance_m,
                SUM(CASE WHEN status = 'concluida' THEN km_estimados END) AS estimated_distance_km,
                AVG(CASE WHEN status = 'concluida' THEN duracao_segundos END) AS avg_duration_seconds,
                SUM(CASE WHEN status = 'concluida' AND pagamento_status = 'confirmado'
                    THEN 1 ELSE 0 END) AS paid_rides
            FROM corridas
            WHERE mototaxista_email = ? AND criada_em >= ? AND criada_em < ?
            """,
            (driver_email, start_iso, end_iso),
        ).fetchone()
        ride_totals = _record(rides)
        last_day = (end - timedelta(microseconds=1)).date()
        expense = connection.execute(
            """
            SELECT COALESCE(SUM(valor_centavos), 0) AS total
            FROM despesas
            WHERE mototaxista_email = ? AND data_despesa >= ? AND data_despesa <= ?
            """,
            (driver_email, start.date().isoformat(), last_day.isoformat()),
        ).fetchone()
        offers = connection.execute(
            """
            SELECT
                SUM(CASE WHEN resposta = 'aceita' THEN 1 ELSE 0 END) AS accepted,
                SUM(CASE WHEN resposta IN ('aceita', 'recusada', 'expirada') THEN 1 ELSE 0 END) AS answered
            FROM ofertas_corrida
            WHERE mototaxista_email = ? AND oferecida_em >= ? AND oferecida_em < ?
            """,
            (driver_email, start_iso, end_iso),
        ).fetchone()
        rating = connection.execute(
            """
            SELECT AVG(estrelas) AS average, COUNT(*) AS total
            FROM avaliacoes_corrida
            WHERE mototaxista_email = ? AND autorizada = 1 AND criada_em >= ? AND criada_em < ?
            """,
            (driver_email, start_iso, end_iso),
        ).fetchone()
        availability_online = _availability_online(connection, driver_email)
        chart_end_day = (end - timedelta(microseconds=1)).date()
        chart_start = _date_start(chart_end_day - timedelta(days=chart_days - 1))
        chart_start_iso = _utc_iso(chart_start)
        daily = connection.execute(
            """
            SELECT substr(criada_em, 1, 10) AS day,
                COUNT(*) AS rides,
                SUM(CASE WHEN status = 'concluida' THEN distancia_gps_m ELSE 0 END) AS gps_distance_m
            FROM corridas
            WHERE mototaxista_email = ? AND criada_em >= ? AND criada_em < ?
            GROUP BY substr(criada_em, 1, 10)
            """,
            (driver_email, chart_start_iso, end_iso),
        ).fetchall()
        paid_daily = connection.execute(
            """
            SELECT substr(finalizada_em, 1, 10) AS day, SUM(valor_centavos) AS cents
            FROM corridas
            WHERE mototaxista_email = ? AND status = 'concluida'
                AND pagamento_status = 'confirmado'
                AND finalizada_em >= ? AND finalizada_em < ?
            GROUP BY substr(finalizada_em, 1, 10)
            """,
            (driver_email, chart_start_iso, end_iso),
        ).fetchall()
        expense_daily = connection.execute(
            """
            SELECT data_despesa AS day, SUM(valor_centavos) AS cents
            FROM despesas
            WHERE mototaxista_email = ? AND data_despesa >= ? AND data_despesa <= ?
            GROUP BY data_despesa
            """,
            (driver_email, chart_start.date().isoformat(), chart_end_day.isoformat()),
        ).fetchall()
        rides_by_day = {row["day"]: row for row in daily}
        paid_by_day = {row["day"]: row["cents"] or 0 for row in paid_daily}
        expenses_by_day = {row["day"]: row["cents"] or 0 for row in expense_daily}
        chart = []
        for offset in range(chart_days):
            day = chart_start.date() + timedelta(days=offset)
            row = rides_by_day.get(day.isoformat(), {})
            chart.append(
                {
                    "date": day.isoformat(),
                    "rides": row.get("rides", 0),
                    "paid_cents": paid_by_day.get(day.isoformat(), 0),
                    "expenses_cents": expenses_by_day.get(day.isoformat(), 0),
                    "gps_distance_m": row.get("gps_distance_m", 0) or 0,
                }
            )
        paid_cents = ride_totals.get("paid_cents") or 0
        paid_rides = ride_totals.get("paid_rides") or 0
        requested_rides = ride_totals.get("requested") or 0
        cancelled_rides = ride_totals.get("cancelled") or 0
        expense_cents = _record(expense).get("total") or 0
        offer_row = _record(offers)
        answered = offer_row.get("answered") or 0
        online_seconds = _online_seconds(connection, driver_email, start, end)
        average_rating = _record(rating)
        return {
            "period": {"from": start_iso, "to": end_iso},
            "availability": availability_online,
            "metrics": {
                "requested_rides": ride_totals.get("requested") or 0,
                "completed_rides": ride_totals.get("completed") or 0,
                "cancelled_rides": ride_totals.get("cancelled") or 0,
                "in_progress_rides": ride_totals.get("in_progress") or 0,
                "cancellation_rate": (
                    cancelled_rides / requested_rides if requested_rides else None
                ),
                "confirmed_earnings_cents": paid_cents,
                "pending_payments_cents": ride_totals.get("pending_cents") or 0,
                "average_ticket_cents": (
                    round(paid_cents / paid_rides) if paid_rides else None
                ),
                "expenses_cents": expense_cents,
                "net_cents": paid_cents - expense_cents,
                "gps_distance_m": ride_totals.get("gps_distance_m") or 0,
                "estimated_distance_km": ride_totals.get("estimated_distance_km"),
                "average_duration_seconds": ride_totals.get("avg_duration_seconds"),
                "acceptance_rate": (
                    (offer_row.get("accepted") or 0) / answered if answered else None
                ),
                "online_seconds": online_seconds,
                "earnings_per_online_hour_cents": (
                    round(paid_cents * 3600 / online_seconds) if online_seconds else None
                ),
                "average_rating": average_rating.get("average"),
                "rating_count": average_rating.get("total") or 0,
            },
            "chart": chart,
        }

    @router.post("/api/rides", status_code=201)
    def create_ride(
        payload: RideRequest,
        customer: dict[str, Any] = Depends(require_customer),
    ) -> dict[str, Any]:
        if payload.is_immediate:
            scheduled = _now()
        else:
            scheduled = payload.scheduled_at
            if scheduled is None or scheduled.tzinfo is None:
                raise HTTPException(
                    status_code=422,
                    detail="Informe uma data e horário futuros com fuso horário.",
                )
            scheduled = scheduled.astimezone(timezone.utc)
            if scheduled <= _now():
                raise HTTPException(
                    status_code=422,
                    detail="Escolha uma data e horário futuros para a corrida.",
                )

        service_type = payload.service_type if payload.service_type in ("passageiro", "pedido") else "passageiro"
        pickup, destination = payload.pickup.strip(), payload.destination.strip()
        if service_type == "pedido":
            passenger_name = " ".join(str(customer.get("name") or "").split())
            passenger_phone = str(customer.get("phone") or "")
        elif payload.for_another_person:
            passenger_name = " ".join((payload.passenger_name or "").split())
            passenger_phone = payload.passenger_phone or ""
        else:
            passenger_name = " ".join(str(customer.get("name") or "").split())
            passenger_phone = str(customer.get("phone") or "")

        if len(passenger_name) < 2:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Atualize seu nome no cadastro para enviar um pedido."
                    if service_type == "pedido"
                    else (
                        "Informe o nome completo do passageiro."
                        if payload.for_another_person
                        else "Atualize seu nome no cadastro para solicitar uma corrida."
                    )
                ),
            )
        if len(pickup) < 3 or len(destination) < 3:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Informe os endereços de retirada e entrega."
                    if service_type == "pedido"
                    else "Informe os endereços de embarque e destino."
                ),
            )
        phone_digits = re.sub(r"\D", "", passenger_phone)
        if len(phone_digits) != 11:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Atualize seu celular com DDD no cadastro para enviar um pedido."
                    if service_type == "pedido"
                    else (
                        "Informe um celular brasileiro válido para o passageiro."
                        if payload.for_another_person
                        else "Atualize seu celular com DDD no cadastro para solicitar uma corrida."
                    )
                ),
            )
        coordinates = (
            payload.pickup_lat,
            payload.pickup_lng,
            payload.destination_lat,
            payload.destination_lng,
        )
        if not all(math.isfinite(value) for value in coordinates):
            raise HTTPException(status_code=422, detail="Selecione locais válidos no mapa.")
        if not (
            _is_within_serra_talhada(payload.pickup_lat, payload.pickup_lng)
            and _is_within_serra_talhada(payload.destination_lat, payload.destination_lng)
        ):
            raise HTTPException(
                status_code=422,
                detail="A origem e o destino devem estar dentro do município de Serra Talhada.",
            )
        if (
            re.sub(r"\s+", " ", pickup).casefold()
            == re.sub(r"\s+", " ", destination).casefold()
            or _distance_meters(*coordinates) < 5
        ):
            raise HTTPException(
                status_code=422,
                detail="Origem e destino precisam ser locais diferentes.",
            )

        idempotency_key = str(payload.idempotency_key)
        request_fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "customer": customer["email"].casefold(),
                    "service_type": service_type,
                    "pickup": pickup,
                    "destination": destination,
                    "coordinates": coordinates,
                    "passenger_name": passenger_name,
                    "passenger_phone": phone_digits,
                    "scheduled_at": None if payload.is_immediate else _utc_iso(scheduled),
                    "is_immediate": payload.is_immediate,
                    "for_another_person": payload.for_another_person if service_type == "passageiro" else False,
                    "payment_method": payload.payment_method,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        def find_existing(connection: Any) -> Any:
            return connection.execute(
                """
                SELECT id, codigo, status, pagamento_status, valor_centavos,
                    cliente_email, hash_solicitacao, tipo_servico
                FROM corridas WHERE chave_idempotencia = ?
                """,
                (idempotency_key,),
            ).fetchone()

        def existing_result(row: Any) -> dict[str, Any]:
            if (
                row["cliente_email"].casefold() != customer["email"].casefold()
                or row["hash_solicitacao"] != request_fingerprint
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Esta chave já foi usada em outra solicitação. Revise os dados e tente novamente.",
                )
            return {
                "id": row["id"],
                "code": row["codigo"],
                "status": row["status"],
                "payment_status": row["pagamento_status"],
                "amount_cents": row["valor_centavos"],
                "service_type": row.get("tipo_servico") or "passageiro",
                "duplicate": True,
            }

        code = f"VZ-{secrets.token_hex(4).upper()}"
        created_at = _utc_iso()
        with database_session() as connection:
            existing = find_existing(connection)
            if existing is not None:
                return existing_result(existing)
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO corridas
                        (codigo, cliente_email, criada_em, agendada_para, embarque, destino,
                         embarque_lat, embarque_lng, destino_lat, destino_lng,
                         passageiro_nome, passageiro_telefone, valor_centavos, forma_pagamento,
                         status, pagamento_status, chave_idempotencia, hash_solicitacao, tipo_servico)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'solicitada', 'pendente', ?, ?, ?)
                    """,
                    (
                        code,
                        customer["email"],
                        created_at,
                        _utc_iso(scheduled),
                        pickup,
                        destination,
                        payload.pickup_lat,
                        payload.pickup_lng,
                        payload.destination_lat,
                        payload.destination_lng,
                        passenger_name,
                        phone_digits,
                        BASE_FARE_CENTS,
                        payload.payment_method,
                        idempotency_key,
                        request_fingerprint,
                        service_type,
                    ),
                )
            except sqlite3.IntegrityError:
                existing = find_existing(connection)
                if existing is None:
                    raise
                return existing_result(existing)
            ride_id = cursor.lastrowid
            _expire_stale_drivers(connection)
            drivers = connection.execute(
                """
                SELECT mototaxista_email FROM disponibilidade_mototaxista
                WHERE online = 1
                """
            ).fetchall()
            notif_title = "Nova corrida — Pedido" if service_type == "pedido" else "Nova corrida — Passageiro"
            notif_msg = f"Há um novo pedido disponível ({code})." if service_type == "pedido" else f"Há uma nova corrida disponível ({code})."
            for driver in drivers:
                _notify(
                    connection,
                    driver["mototaxista_email"],
                    "corrida_disponivel",
                    notif_title,
                    notif_msg,
                )
        return {
            "id": ride_id,
            "code": code,
            "status": "solicitada",
            "payment_status": "pendente",
            "amount_cents": BASE_FARE_CENTS,
            "service_type": service_type,
            "duplicate": False,
        }

    @router.get("/api/rides/mine")
    def customer_rides(customer: dict[str, Any] = Depends(require_customer)) -> dict[str, Any]:
        with database_session() as connection:
            rows = connection.execute(
                """
                SELECT id, codigo, criada_em, agendada_para, embarque, destino,
                    valor_centavos, forma_pagamento, pagamento_status, status, tipo_servico
                FROM corridas WHERE cliente_email = ?
                ORDER BY criada_em DESC LIMIT 100
                """,
                (customer["email"],),
            ).fetchall()
        return {"rides": [_ride_payload(row) | {"code": row["codigo"]} for row in rows]}

    @router.post("/api/rides/{ride_id}/cancel")
    def cancel_customer_ride(
        ride_id: int,
        customer: dict[str, Any] = Depends(require_customer),
    ) -> dict[str, bool]:
        with database_session() as connection:
            cursor = connection.execute(
                """
                UPDATE corridas SET status = 'cancelada', cancelada_em = ?
                WHERE id = ? AND cliente_email = ? AND status = 'solicitada'
                """,
                (_utc_iso(), ride_id, customer["email"]),
            )
            if cursor.rowcount != 1:
                raise HTTPException(status_code=404, detail="Corrida não encontrada ou não pode ser cancelada.")
        return {"ok": True}

    @router.get("/api/driver/dashboard")
    def get_dashboard(
        period: Literal["hoje", "7dias", "30dias"] = "7dias",
        start_date: date | None = Query(default=None, alias="from"),
        end_date: date | None = Query(default=None, alias="to"),
        driver: dict[str, Any] = Depends(require_driver),
    ) -> dict[str, Any]:
        start, end, days = _period_bounds(period, start_date, end_date)
        chart_days = min(days, 30)
        with database_session() as connection:
            return dashboard_data(connection, driver["email"], start, end, chart_days)

    @router.get("/api/driver/rides/available")
    def available_rides(driver: dict[str, Any] = Depends(require_driver)) -> dict[str, Any]:
        with database_session() as connection:
            online = _availability_online(connection, driver["email"])
            rows = connection.execute(
                """
                SELECT id, codigo, criada_em, agendada_para, embarque, destino,
                    valor_centavos, forma_pagamento, tipo_servico
                FROM corridas c WHERE status = 'solicitada'
                    AND NOT EXISTS (
                        SELECT 1 FROM ofertas_corrida o
                        WHERE o.corrida_id = c.id AND o.mototaxista_email = ?
                            AND o.resposta = 'recusada'
                    )
                ORDER BY agendada_para, id LIMIT 100
                    """,
                    (driver["email"],),
            ).fetchall()
            if not online:
                rows = []
            else:
                for row in rows:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO ofertas_corrida
                            (corrida_id, mototaxista_email, oferecida_em)
                        VALUES (?, ?, ?)
                        """,
                        (row["id"], driver["email"], _utc_iso()),
                    )
        return {
            "rides": [
                {
                    "id": row["id"],
                    "code": row["codigo"],
                    "created_at": row["criada_em"],
                    "scheduled_at": row["agendada_para"],
                    "pickup": row["embarque"],
                    "destination": row["destino"],
                    "amount_cents": row["valor_centavos"],
                    "payment_method": row["forma_pagamento"],
                    "service_type": row.get("tipo_servico") or "passageiro",
                }
                for row in rows
            ]
        }

    @router.get("/api/driver/rides")
    def driver_rides(
        status: RideStatus | None = None,
        start_date: date | None = Query(default=None, alias="from"),
        end_date: date | None = Query(default=None, alias="to"),
        page: int = Query(default=1, ge=1, le=10_000),
        page_size: int = Query(default=20, ge=1, le=100),
        driver: dict[str, Any] = Depends(require_driver),
    ) -> dict[str, Any]:
        if start_date is None and end_date is None:
            today = _now().date()
            start = _date_start(today - timedelta(days=365))
            end = _date_start(today + timedelta(days=1))
        else:
            start, end, _ = _period_bounds("30dias", start_date, end_date)
        conditions = ["mototaxista_email = ?", "criada_em >= ?", "criada_em < ?"]
        values: list[Any] = [driver["email"], _utc_iso(start), _utc_iso(end)]
        if status:
            conditions.append("status = ?")
            values.append(status)
        where = " AND ".join(conditions)
        with database_session() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) AS total FROM corridas WHERE {where}", values
            ).fetchone()["total"]
            rows = connection.execute(
                f"""
                SELECT id, codigo, criada_em, agendada_para, embarque, destino,
                    valor_centavos, forma_pagamento, pagamento_status, status,
                    distancia_gps_m, duracao_segundos, finalizada_em, tipo_servico
                FROM corridas WHERE {where}
                ORDER BY criada_em DESC, id DESC LIMIT ? OFFSET ?
                """,
                [*values, page_size, (page - 1) * page_size],
            ).fetchall()
        return {
            "rides": [_ride_payload(row) | {"code": row["codigo"]} for row in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    @router.get("/api/driver/rides/{ride_id}")
    def ride_detail(
        ride_id: int,
        driver: dict[str, Any] = Depends(require_driver),
    ) -> dict[str, Any]:
        with database_session() as connection:
            row = connection.execute(
                """
                SELECT r.*
                FROM corridas r
                WHERE r.id = ? AND r.mototaxista_email = ?
                """,
                (ride_id, driver["email"]),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Corrida não encontrada.")
        return {
            "id": row["id"],
            "code": row["codigo"],
            "created_at": row["criada_em"],
            "scheduled_at": row["agendada_para"],
            "pickup": row["embarque"],
            "destination": row["destino"],
            "amount_cents": row["valor_centavos"],
            "payment_method": row["forma_pagamento"],
            "payment_status": row["pagamento_status"],
            "status": row["status"],
            "gps_distance_m": row["distancia_gps_m"],
            "duration_seconds": row["duracao_segundos"],
            "completed_at": row["finalizada_em"],
            "passenger_name": row["passageiro_nome"],
            "passenger_phone": row["passageiro_telefone"],
            "accepted_at": row["aceita_em"],
            "started_at": row["iniciou_em"],
            "service_type": row.get("tipo_servico") or "passageiro",
        }

    @router.post("/api/driver/rides/{ride_id}/accept")
    def accept_ride(
        ride_id: int,
        driver: dict[str, Any] = Depends(require_driver),
    ) -> dict[str, Any]:
        with database_session() as connection:
            if not _availability_online(connection, driver["email"]):
                raise HTTPException(status_code=409, detail="Fique online antes de aceitar uma corrida.")
            now = _utc_iso()
            cursor = connection.execute(
                """
                UPDATE corridas SET mototaxista_email = ?, status = 'aceita', aceita_em = ?
                WHERE id = ? AND status = 'solicitada'
                """,
                (driver["email"], now, ride_id),
            )
            if cursor.rowcount != 1:
                raise HTTPException(status_code=409, detail="Esta corrida já foi aceita ou não está disponível.")
            connection.execute(
                """
                INSERT INTO ofertas_corrida
                    (corrida_id, mototaxista_email, oferecida_em, resposta, respondida_em)
                VALUES (?, ?, ?, 'aceita', ?)
                ON CONFLICT(corrida_id, mototaxista_email)
                DO UPDATE SET resposta = 'aceita', respondida_em = excluded.respondida_em
                """,
                (ride_id, driver["email"], now, now),
            )
            _notify(connection, driver["email"], "corrida_aceita", "Corrida aceita", "A corrida foi vinculada à sua conta.")
        return {"ok": True, "status": "aceita"}

    @router.patch("/api/driver/rides/{ride_id}/status")
    def update_ride_status(
        ride_id: int,
        payload: RideStatusRequest,
        driver: dict[str, Any] = Depends(require_driver),
    ) -> dict[str, str]:
        now = _utc_iso()
        with database_session() as connection:
            ride = connection.execute(
                """
                SELECT status, iniciou_em FROM corridas
                WHERE id = ? AND mototaxista_email = ?
                """,
                (ride_id, driver["email"]),
            ).fetchone()
            if ride is None:
                raise HTTPException(status_code=404, detail="Corrida não encontrada.")
            expected = {
                "em_andamento": {"aceita"},
                "concluida": {"em_andamento"},
                "cancelada": {"aceita", "em_andamento"},
            }[payload.status]
            if ride["status"] not in expected:
                raise HTTPException(status_code=409, detail="A transição de status solicitada não é permitida.")
            if payload.status == "em_andamento":
                connection.execute(
                    "UPDATE corridas SET status = ?, iniciou_em = ? WHERE id = ?",
                    (payload.status, now, ride_id),
                )
            elif payload.status == "concluida":
                started = datetime.fromisoformat(ride["iniciou_em"])
                duration = max(0, int((_now() - started).total_seconds()))
                connection.execute(
                    """
                    UPDATE corridas SET status = ?, finalizada_em = ?, duracao_segundos = ?
                    WHERE id = ?
                    """,
                    (payload.status, now, duration, ride_id),
                )
            else:
                connection.execute(
                    "UPDATE corridas SET status = ?, cancelada_em = ? WHERE id = ?",
                    (payload.status, now, ride_id),
                )
            if payload.status == "concluida":
                _notify(
                    connection,
                    driver["email"],
                    "pagamento_pendente",
                    "Pagamento pendente",
                    "A corrida foi concluída; o pagamento permanece pendente até confirmação.",
                )
        return {"status": payload.status}

    @router.post("/api/driver/rides/{ride_id}/decline")
    def decline_ride(
        ride_id: int,
        driver: dict[str, Any] = Depends(require_driver),
    ) -> dict[str, bool]:
        with database_session() as connection:
            offer = connection.execute(
                """
                SELECT o.id, c.status FROM ofertas_corrida o
                JOIN corridas c ON c.id = o.corrida_id
                WHERE o.corrida_id = ? AND o.mototaxista_email = ?
                """,
                (ride_id, driver["email"]),
            ).fetchone()
            if offer is None or offer["status"] != "solicitada":
                raise HTTPException(status_code=404, detail="Oferta não encontrada ou indisponível.")
            if not connection.execute(
                """
                UPDATE ofertas_corrida SET resposta = 'recusada', respondida_em = ?
                WHERE id = ? AND resposta = 'pendente'
                """,
                (_utc_iso(), offer["id"]),
            ).rowcount:
                raise HTTPException(status_code=409, detail="Esta oferta já foi respondida.")
        return {"ok": True}

    @router.get("/api/driver/availability")
    def get_availability(driver: dict[str, Any] = Depends(require_driver)) -> dict[str, Any]:
        with database_session() as connection:
            row = connection.execute(
                """
                SELECT online, alterada_em FROM disponibilidade_mototaxista
                WHERE mototaxista_email = ?
                """,
                (driver["email"],),
            ).fetchone()
            online = _availability_online(connection, driver["email"])
        return {
            "online": online,
            "changed_at": row["alterada_em"] if row else None,
        }

    @router.put("/api/driver/availability")
    def set_availability(
        payload: AvailabilityRequest,
        driver: dict[str, Any] = Depends(require_driver),
    ) -> dict[str, Any]:
        now = _utc_iso()
        with database_session() as connection:
            _availability_online(connection, driver["email"])
            current = connection.execute(
                """
                SELECT online FROM disponibilidade_mototaxista
                WHERE mototaxista_email = ?
                """,
                (driver["email"],),
            ).fetchone()
            active_ride = connection.execute(
                """
                SELECT id FROM corridas
                WHERE mototaxista_email = ? AND status = 'em_andamento' LIMIT 1
                """,
                (driver["email"],),
            ).fetchone()
            active_delivery = connection.execute(
                """
                SELECT id FROM entregas
                WHERE mototaxista_email = ? AND status IN (
                    'aceita', 'a_caminho_retirada', 'chegada_retirada',
                    'coletado', 'em_transito', 'chegada_destino'
                ) LIMIT 1
                """,
                (driver["email"],),
            ).fetchone()
            if (active_ride or active_delivery) and not payload.online:
                raise HTTPException(
                    status_code=409,
                    detail="Conclua a corrida ou entrega ativa antes de ficar offline.",
                )
            current_online = bool(current and current["online"])
            if current_online != payload.online:
                connection.execute(
                    """
                    INSERT INTO disponibilidade_mototaxista
                        (mototaxista_email, online, alterada_em, last_seen_em)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(mototaxista_email)
                    DO UPDATE SET online = excluded.online, alterada_em = excluded.alterada_em,
                        last_seen_em = excluded.last_seen_em
                    """,
                    (driver["email"], int(payload.online), now, now if payload.online else None),
                )
                connection.execute(
                    """
                    INSERT INTO eventos_disponibilidade
                        (mototaxista_email, online, registrada_em)
                    VALUES (?, ?, ?)
                    """,
                    (driver["email"], int(payload.online), now),
                )
        return {"online": payload.online, "changed_at": now}

    @router.post("/api/driver/availability/heartbeat")
    def availability_heartbeat(driver: dict[str, Any] = Depends(require_driver)) -> dict[str, bool]:
        with database_session() as connection:
            online = _availability_online(connection, driver["email"])
        return {"online": online}

    @router.get("/api/driver/expenses")
    def list_expenses(
        start_date: date | None = Query(default=None, alias="from"),
        end_date: date | None = Query(default=None, alias="to"),
        driver: dict[str, Any] = Depends(require_driver),
    ) -> dict[str, Any]:
        start, end, _ = _period_bounds("30dias", start_date, end_date)
        last_day = (end - timedelta(microseconds=1)).date()
        with database_session() as connection:
            rows = connection.execute(
                """
                SELECT id, categoria, descricao, valor_centavos, data_despesa,
                    criada_em, atualizada_em
                FROM despesas
                WHERE mototaxista_email = ? AND data_despesa >= ? AND data_despesa <= ?
                ORDER BY data_despesa DESC, id DESC
                LIMIT 1000
                """,
                (driver["email"], start.date().isoformat(), last_day.isoformat()),
            ).fetchall()
        return {
            "expenses": [
                {
                    "id": row["id"],
                    "category": row["categoria"],
                    "description": row["descricao"],
                    "amount_cents": row["valor_centavos"],
                    "spent_on": row["data_despesa"],
                    "created_at": row["criada_em"],
                    "updated_at": row["atualizada_em"],
                }
                for row in rows
            ]
        }

    @router.post("/api/driver/expenses", status_code=201)
    def create_expense(
        payload: ExpenseRequest,
        driver: dict[str, Any] = Depends(require_driver),
    ) -> dict[str, Any]:
        if payload.spent_on > _now().date():
            raise HTTPException(status_code=422, detail="A data da despesa não pode estar no futuro.")
        now = _utc_iso()
        description = payload.description.strip()
        if len(description) < 2:
            raise HTTPException(status_code=422, detail="Informe uma descrição válida.")
        with database_session() as connection:
            cursor = connection.execute(
                """
                INSERT INTO despesas
                    (mototaxista_email, categoria, descricao, valor_centavos,
                     data_despesa, criada_em, atualizada_em)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    driver["email"],
                    payload.category,
                    description,
                    payload.amount_cents,
                    payload.spent_on.isoformat(),
                    now,
                    now,
                ),
            )
            expense_id = cursor.lastrowid
        return {"id": expense_id, "ok": True}

    @router.put("/api/driver/expenses/{expense_id}")
    def update_expense(
        expense_id: int,
        payload: ExpenseRequest,
        driver: dict[str, Any] = Depends(require_driver),
    ) -> dict[str, bool]:
        if payload.spent_on > _now().date():
            raise HTTPException(status_code=422, detail="A data da despesa não pode estar no futuro.")
        description = payload.description.strip()
        if len(description) < 2:
            raise HTTPException(status_code=422, detail="Informe uma descrição válida.")
        with database_session() as connection:
            cursor = connection.execute(
                """
                UPDATE despesas SET categoria = ?, descricao = ?, valor_centavos = ?,
                    data_despesa = ?, atualizada_em = ?
                WHERE id = ? AND mototaxista_email = ?
                """,
                (
                    payload.category,
                    description,
                    payload.amount_cents,
                    payload.spent_on.isoformat(),
                    _utc_iso(),
                    expense_id,
                    driver["email"],
                ),
            )
            if cursor.rowcount != 1:
                raise HTTPException(status_code=404, detail="Despesa não encontrada.")
        return {"ok": True}

    @router.delete("/api/driver/expenses/{expense_id}")
    def delete_expense(
        expense_id: int,
        driver: dict[str, Any] = Depends(require_driver),
    ) -> dict[str, bool]:
        with database_session() as connection:
            cursor = connection.execute(
                "DELETE FROM despesas WHERE id = ? AND mototaxista_email = ?",
                (expense_id, driver["email"]),
            )
            if cursor.rowcount != 1:
                raise HTTPException(status_code=404, detail="Despesa não encontrada.")
        return {"ok": True}

    @router.get("/api/driver/goals")
    def list_goals(driver: dict[str, Any] = Depends(require_driver)) -> dict[str, Any]:
        with database_session() as connection:
            rows = connection.execute(
                """
                SELECT periodo, meta_centavos, meta_corridas, atualizada_em
                FROM metas_mototaxista WHERE mototaxista_email = ?
                ORDER BY CASE periodo WHEN 'diaria' THEN 1 WHEN 'semanal' THEN 2 ELSE 3 END
                """,
                (driver["email"],),
            ).fetchall()
        return {
            "goals": [
                {
                    "period": row["periodo"],
                    "target_cents": row["meta_centavos"],
                    "target_rides": row["meta_corridas"],
                    "updated_at": row["atualizada_em"],
                }
                for row in rows
            ]
        }

    @router.put("/api/driver/goals")
    def save_goal(
        payload: GoalRequest,
        driver: dict[str, Any] = Depends(require_driver),
    ) -> dict[str, bool]:
        if payload.target_cents is None and payload.target_rides is None:
            raise HTTPException(status_code=422, detail="Defina ao menos uma meta de ganhos ou corridas.")
        with database_session() as connection:
            connection.execute(
                """
                INSERT INTO metas_mototaxista
                    (mototaxista_email, periodo, meta_centavos, meta_corridas, atualizada_em)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(mototaxista_email, periodo)
                DO UPDATE SET meta_centavos = excluded.meta_centavos,
                    meta_corridas = excluded.meta_corridas, atualizada_em = excluded.atualizada_em
                """,
                (
                    driver["email"],
                    payload.period,
                    payload.target_cents,
                    payload.target_rides,
                    _utc_iso(),
                ),
            )
        return {"ok": True}

    @router.get("/api/driver/notifications")
    def list_notifications(
        unread_only: bool = False,
        page: int = Query(default=1, ge=1, le=10_000),
        page_size: int = Query(default=30, ge=1, le=100),
        driver: dict[str, Any] = Depends(require_driver),
    ) -> dict[str, Any]:
        where = "mototaxista_email = ?"
        values: list[Any] = [driver["email"]]
        if unread_only:
            where += " AND lida_em IS NULL"
        with database_session() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) AS total FROM notificacoes_mototaxista WHERE {where}",
                values,
            ).fetchone()["total"]
            unread = connection.execute(
                """
                SELECT COUNT(*) AS total FROM notificacoes_mototaxista
                WHERE mototaxista_email = ? AND lida_em IS NULL
                """,
                (driver["email"],),
            ).fetchone()["total"]
            rows = connection.execute(
                f"""
                SELECT id, tipo, titulo, mensagem, criada_em, lida_em
                FROM notificacoes_mototaxista WHERE {where}
                ORDER BY criada_em DESC, id DESC LIMIT ? OFFSET ?
                """,
                [*values, page_size, (page - 1) * page_size],
            ).fetchall()
        return {
            "unread": unread,
            "total": total,
            "notifications": [
                {
                    "id": row["id"],
                    "type": row["tipo"],
                    "title": row["titulo"],
                    "message": row["mensagem"],
                    "created_at": row["criada_em"],
                    "read_at": row["lida_em"],
                }
                for row in rows
            ],
        }

    @router.patch("/api/driver/notifications/read-all")
    def mark_all_notifications_read(driver: dict[str, Any] = Depends(require_driver)) -> dict[str, bool]:
        with database_session() as connection:
            connection.execute(
                """
                UPDATE notificacoes_mototaxista SET lida_em = ?
                WHERE mototaxista_email = ? AND lida_em IS NULL
                """,
                (_utc_iso(), driver["email"]),
            )
        return {"ok": True}

    @router.patch("/api/driver/notifications/{notification_id}/read")
    def mark_notification_read(
        notification_id: int,
        driver: dict[str, Any] = Depends(require_driver),
    ) -> dict[str, bool]:
        with database_session() as connection:
            cursor = connection.execute(
                """
                UPDATE notificacoes_mototaxista SET lida_em = ?
                WHERE id = ? AND mototaxista_email = ? AND lida_em IS NULL
                """,
                (_utc_iso(), notification_id, driver["email"]),
            )
            if cursor.rowcount != 1:
                exists = connection.execute(
                    """
                    SELECT id FROM notificacoes_mototaxista
                    WHERE id = ? AND mototaxista_email = ?
                    """,
                    (notification_id, driver["email"]),
                ).fetchone()
                if exists is None:
                    raise HTTPException(status_code=404, detail="Notificação não encontrada.")
        return {"ok": True}

    @router.get("/api/driver/rides/{ride_id}/gps")
    def get_ride_gps(
        ride_id: int,
        driver: dict[str, Any] = Depends(require_driver),
    ) -> dict[str, Any]:
        with database_session() as connection:
            ride = connection.execute(
                """
                SELECT id, distancia_gps_m, status FROM corridas
                WHERE id = ? AND mototaxista_email = ?
                """,
                (ride_id, driver["email"]),
            ).fetchone()
            if ride is None:
                raise HTTPException(status_code=404, detail="Corrida não encontrada.")
            points = connection.execute(
                """
                SELECT latitude, longitude, precisao_m, registrada_em
                FROM pontos_gps
                WHERE corrida_id = ? AND mototaxista_email = ?
                ORDER BY registrada_em, id
                LIMIT 5000
                """,
                (ride_id, driver["email"]),
            ).fetchall()
        return {
            "ride_id": ride_id,
            "status": ride["status"],
            "distance_m": ride["distancia_gps_m"],
            "points": [
                {
                    "latitude": point["latitude"],
                    "longitude": point["longitude"],
                    "accuracy_m": point["precisao_m"],
                    "recorded_at": point["registrada_em"],
                }
                for point in points
            ],
        }

    @router.post("/api/driver/rides/{ride_id}/gps", status_code=201)
    def record_ride_gps(
        ride_id: int,
        payload: GpsPointRequest,
        driver: dict[str, Any] = Depends(require_driver),
    ) -> dict[str, Any]:
        recorded_at = payload.recorded_at or _now()
        if recorded_at.tzinfo is None:
            recorded_at = recorded_at.replace(tzinfo=timezone.utc)
        recorded_at = recorded_at.astimezone(timezone.utc)
        if abs((_now() - recorded_at).total_seconds()) > 60:
            raise HTTPException(status_code=422, detail="O horário do ponto GPS está fora do intervalo permitido.")
        point_time = _utc_iso(recorded_at)
        with database_session() as connection:
            ride = connection.execute(
                """
                SELECT status FROM corridas
                WHERE id = ? AND mototaxista_email = ?
                """,
                (ride_id, driver["email"]),
            ).fetchone()
            if ride is None:
                raise HTTPException(status_code=404, detail="Corrida não encontrada.")
            if ride["status"] != "em_andamento":
                raise HTTPException(status_code=409, detail="O GPS só pode ser registrado durante uma corrida ativa.")
            if not _is_within_serra_talhada(payload.latitude, payload.longitude):
                raise HTTPException(
                    status_code=422,
                    detail="O rastreamento GPS só pode registrar localizações dentro de Serra Talhada.",
                )
            previous = connection.execute(
                """
                SELECT latitude, longitude, registrada_em FROM pontos_gps
                WHERE corrida_id = ? AND mototaxista_email = ?
                ORDER BY registrada_em DESC, id DESC LIMIT 1
                """,
                (ride_id, driver["email"]),
            ).fetchone()
            if previous:
                last_time = datetime.fromisoformat(previous["registrada_em"])
                interval = (recorded_at - last_time).total_seconds()
                if interval < 3:
                    raise HTTPException(status_code=429, detail="Aguarde antes de enviar outro ponto GPS.")
                segment = _distance_meters(
                    previous["latitude"],
                    previous["longitude"],
                    payload.latitude,
                    payload.longitude,
                )
                if 3 <= interval <= 300 and segment / interval <= 70:
                    connection.execute(
                        "UPDATE corridas SET distancia_gps_m = distancia_gps_m + ? WHERE id = ?",
                        (round(segment), ride_id),
                    )
            connection.execute(
                """
                INSERT INTO pontos_gps
                    (corrida_id, mototaxista_email, latitude, longitude, precisao_m, registrada_em)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    ride_id,
                    driver["email"],
                    payload.latitude,
                    payload.longitude,
                    payload.accuracy_m,
                    point_time,
                ),
            )
            distance = connection.execute(
                "SELECT distancia_gps_m FROM corridas WHERE id = ?",
                (ride_id,),
            ).fetchone()["distancia_gps_m"]
        return {"ok": True, "distance_m": distance}

    @router.get("/api/driver/reviews")
    def list_reviews(driver: dict[str, Any] = Depends(require_driver)) -> dict[str, Any]:
        with database_session() as connection:
            summary = connection.execute(
                """
                SELECT AVG(estrelas) AS average, COUNT(*) AS total
                FROM avaliacoes_corrida
                WHERE mototaxista_email = ? AND autorizada = 1
                """,
                (driver["email"],),
            ).fetchone()
            distribution = connection.execute(
                """
                SELECT estrelas, COUNT(*) AS total
                FROM avaliacoes_corrida
                WHERE mototaxista_email = ? AND autorizada = 1
                GROUP BY estrelas
                """,
                (driver["email"],),
            ).fetchall()
            reviews = connection.execute(
                """
                SELECT a.estrelas, a.comentario, a.criada_em, c.codigo
                FROM avaliacoes_corrida a JOIN corridas c ON c.id = a.corrida_id
                WHERE a.mototaxista_email = ? AND a.autorizada = 1
                ORDER BY a.criada_em DESC LIMIT 100
                """,
                (driver["email"],),
            ).fetchall()
        return {
            "average": summary["average"],
            "total": summary["total"],
            "distribution": {str(row["estrelas"]): row["total"] for row in distribution},
            "reviews": [
                {
                    "stars": row["estrelas"],
                    "comment": row["comentario"],
                    "created_at": row["criada_em"],
                    "ride_code": row["codigo"],
                }
                for row in reviews
            ],
        }

    @router.post("/api/rides/{ride_id}/review", status_code=201)
    def submit_review(
        ride_id: int,
        payload: ReviewRequest,
        customer: dict[str, Any] = Depends(require_customer),
    ) -> dict[str, bool]:
        comment = (payload.comment or "").strip() or None
        with database_session() as connection:
            ride = connection.execute(
                """
                SELECT mototaxista_email, status FROM corridas
                WHERE id = ? AND cliente_email = ?
                """,
                (ride_id, customer["email"]),
            ).fetchone()
            if ride is None or ride["status"] != "concluida" or not ride["mototaxista_email"]:
                raise HTTPException(status_code=404, detail="Corrida concluída não encontrada.")
            try:
                connection.execute(
                    """
                    INSERT INTO avaliacoes_corrida
                        (corrida_id, mototaxista_email, estrelas, comentario, autorizada, criada_em)
                    VALUES (?, ?, ?, ?, 1, ?)
                    """,
                    (ride_id, ride["mototaxista_email"], payload.stars, comment, _utc_iso()),
                )
            except sqlite3.IntegrityError as exc:
                raise HTTPException(status_code=409, detail="Esta corrida já foi avaliada.") from exc
            _notify(
                connection,
                ride["mototaxista_email"],
                "nova_avaliacao",
                "Você recebeu uma avaliação",
                f"Um cliente avaliou sua corrida com {payload.stars} estrela(s).",
            )
        return {"ok": True}

    @router.get("/api/driver/profile")
    def get_profile(driver: dict[str, Any] = Depends(require_driver)) -> dict[str, Any]:
        with database_session() as connection:
            row = connection.execute(
                """
                SELECT nome, email, telefone, idade, moto, placa, foto_mime
                FROM mototaxistas WHERE email = ?
                """,
                (driver["email"],),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Perfil de mototaxista não encontrado.")
        return {
            "name": row["nome"],
            "email": row["email"],
            "phone": row["telefone"],
            "age": row["idade"],
            "motorcycle": row["moto"] or "",
            "plate": row["placa"] or "",
            "photo_url": "/api/driver/profile/photo" if row["foto_mime"] else None,
        }

    @router.put("/api/driver/profile")
    def update_profile(
        payload: ProfileRequest,
        driver: dict[str, Any] = Depends(require_driver),
    ) -> dict[str, bool]:
        phone = payload.phone.strip()
        motorcycle = payload.motorcycle.strip()
        plate = payload.plate.strip().upper()
        if len(re.sub(r"\D", "", phone)) not in {10, 11, 12, 13}:
            raise HTTPException(status_code=422, detail="Informe um celular com DDD válido.")
        if len(motorcycle) < 2:
            raise HTTPException(status_code=422, detail="Informe o modelo da motocicleta.")
        if not re.fullmatch(r"[A-Z]{3}\d[A-Z0-9]\d{2}|[A-Z]{3}\d{4}", plate):
            raise HTTPException(status_code=422, detail="Informe uma placa válida.")
        with database_session() as connection:
            cursor = connection.execute(
                "UPDATE mototaxistas SET telefone = ?, moto = ?, placa = ? WHERE email = ?",
                (phone, motorcycle, plate, driver["email"]),
            )
            if cursor.rowcount != 1:
                raise HTTPException(status_code=404, detail="Perfil de mototaxista não encontrado.")
        return {"ok": True}

    @router.post("/api/driver/profile/photo")
    async def upload_profile_photo(
        request: Request,
        driver: dict[str, Any] = Depends(require_driver),
    ) -> dict[str, bool]:
        media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        signatures = {
            "image/jpeg": lambda data: data.startswith(b"\xff\xd8\xff"),
            "image/png": lambda data: data.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/webp": lambda data: data.startswith(b"RIFF") and data[8:12] == b"WEBP",
        }
        if media_type not in signatures:
            raise HTTPException(status_code=415, detail="Use uma imagem JPEG, PNG ou WebP.")
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > 1_000_000:
                raise HTTPException(status_code=413, detail="A imagem deve ter no máximo 1 MB.")
        image = bytes(content)
        if not image or not signatures[media_type](image):
            raise HTTPException(status_code=415, detail="O conteúdo enviado não corresponde a uma imagem válida.")
        with database_session() as connection:
            cursor = connection.execute(
                """
                UPDATE mototaxistas SET foto_perfil = ?, foto_mime = ? WHERE email = ?
                """,
                (image, media_type, driver["email"]),
            )
            if cursor.rowcount != 1:
                raise HTTPException(status_code=404, detail="Perfil de mototaxista não encontrado.")
        return {"ok": True}

    @router.get("/api/driver/profile/photo")
    def get_profile_photo(driver: dict[str, Any] = Depends(require_driver)) -> Response:
        with database_session() as connection:
            row = connection.execute(
                "SELECT foto_perfil, foto_mime FROM mototaxistas WHERE email = ?",
                (driver["email"],),
            ).fetchone()
        if row is None or not row["foto_perfil"] or row["foto_mime"] not in {
            "image/jpeg",
            "image/png",
            "image/webp",
        }:
            raise HTTPException(status_code=404, detail="Foto de perfil não encontrada.")
        return Response(
            content=row["foto_perfil"],
            media_type=row["foto_mime"],
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        )

    @router.delete("/api/driver/profile/photo")
    def delete_profile_photo(driver: dict[str, Any] = Depends(require_driver)) -> dict[str, bool]:
        with database_session() as connection:
            connection.execute(
                "UPDATE mototaxistas SET foto_perfil = NULL, foto_mime = NULL WHERE email = ?",
                (driver["email"],),
            )
        return {"ok": True}

    def report_rows(
        connection: sqlite3.Connection,
        driver_email: str,
        kind: str,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        start_iso, end_iso = _utc_iso(start), _utc_iso(end)
        first_day = start.date().isoformat()
        last_day = (end - timedelta(microseconds=1)).date().isoformat()
        if kind == "resumo":
            metrics = dashboard_data(connection, driver_email, start, end, min(30, max(1, (end.date() - start.date()).days + 1)))["metrics"]
            return [
                {"indicador": key, "valor": value}
                for key, value in metrics.items()
            ]
        if kind == "corridas":
            rows = connection.execute(
                """
                SELECT codigo, criada_em, agendada_para, embarque, destino, status,
                    forma_pagamento, pagamento_status, valor_centavos, distancia_gps_m,
                    duracao_segundos
                FROM corridas WHERE mototaxista_email = ? AND criada_em >= ? AND criada_em < ?
                ORDER BY criada_em DESC LIMIT 10000
                """,
                (driver_email, start_iso, end_iso),
            ).fetchall()
            return [
                {
                    "codigo": row["codigo"],
                    "criada_em": row["criada_em"],
                    "agendada_para": row["agendada_para"],
                    "embarque": row["embarque"],
                    "destino": row["destino"],
                    "status": row["status"],
                    "forma_pagamento": row["forma_pagamento"],
                    "pagamento_status": row["pagamento_status"],
                    "valor_centavos": row["valor_centavos"],
                    "distancia_gps_m": row["distancia_gps_m"],
                    "duracao_segundos": row["duracao_segundos"],
                }
                for row in rows
            ]
        if kind == "despesas":
            rows = connection.execute(
                """
                SELECT categoria, descricao, valor_centavos, data_despesa
                FROM despesas
                WHERE mototaxista_email = ? AND data_despesa >= ? AND data_despesa <= ?
                ORDER BY data_despesa DESC LIMIT 10000
                """,
                (driver_email, first_day, last_day),
            ).fetchall()
            return [dict(row) for row in rows]
        if kind == "financeiro":
            rides = connection.execute(
                """
                SELECT finalizada_em AS data, 'corrida' AS tipo, codigo AS descricao,
                    valor_centavos, pagamento_status AS status
                FROM corridas
                WHERE mototaxista_email = ? AND status = 'concluida'
                    AND finalizada_em >= ? AND finalizada_em < ?
                ORDER BY finalizada_em DESC LIMIT 10000
                """,
                (driver_email, start_iso, end_iso),
            ).fetchall()
            expenses = connection.execute(
                """
                SELECT data_despesa AS data, 'despesa' AS tipo, descricao,
                    valor_centavos, 'registrada' AS status
                FROM despesas
                WHERE mototaxista_email = ? AND data_despesa >= ? AND data_despesa <= ?
                ORDER BY data_despesa DESC LIMIT 10000
                """,
                (driver_email, first_day, last_day),
            ).fetchall()
            return [
                {
                    "data": row["data"],
                    "tipo": row["tipo"],
                    "descricao": row["descricao"],
                    "valor_centavos": row["valor_centavos"] if row["tipo"] == "corrida" else -row["valor_centavos"],
                    "status": row["status"],
                    "considerado_no_faturamento": (
                        row["status"] == "confirmado" if row["tipo"] == "corrida" else False
                    ),
                }
                for row in [*rides, *expenses]
            ]
        if kind == "desempenho":
            rows = connection.execute(
                """
                SELECT substr(criada_em, 1, 10) AS data,
                    COUNT(*) AS solicitadas,
                    SUM(CASE WHEN status = 'concluida' THEN 1 ELSE 0 END) AS concluidas,
                    SUM(CASE WHEN status = 'cancelada' THEN 1 ELSE 0 END) AS canceladas,
                    SUM(CASE WHEN status = 'concluida' THEN distancia_gps_m ELSE 0 END) AS distancia_gps_m
                FROM corridas
                WHERE mototaxista_email = ? AND criada_em >= ? AND criada_em < ?
                GROUP BY substr(criada_em, 1, 10)
                ORDER BY data
                """,
                (driver_email, start_iso, end_iso),
            ).fetchall()
            return [dict(row) for row in rows]
        if kind == "distancia":
            rows = connection.execute(
                """
                SELECT substr(criada_em, 1, 10) AS data,
                    SUM(CASE WHEN status = 'concluida' THEN distancia_gps_m ELSE 0 END) AS distancia_gps_m,
                    SUM(CASE WHEN status = 'concluida' THEN COALESCE(km_estimados, 0) ELSE 0 END) AS km_estimados
                FROM corridas
                WHERE mototaxista_email = ? AND criada_em >= ? AND criada_em < ?
                GROUP BY substr(criada_em, 1, 10)
                ORDER BY data
                """,
                (driver_email, start_iso, end_iso),
            ).fetchall()
            return [dict(row) for row in rows]
        rows = connection.execute(
            """
            SELECT c.codigo, p.latitude, p.longitude, p.precisao_m, p.registrada_em
            FROM pontos_gps p JOIN corridas c ON c.id = p.corrida_id
            WHERE p.mototaxista_email = ? AND p.registrada_em >= ? AND p.registrada_em < ?
            ORDER BY p.registrada_em LIMIT 10000
            """,
            (driver_email, start_iso, end_iso),
        ).fetchall()
        return [dict(row) for row in rows]

    @router.get("/api/driver/reports.csv")
    def export_csv(
        kind: ReportKind = "resumo",
        start_date: date | None = Query(default=None, alias="from"),
        end_date: date | None = Query(default=None, alias="to"),
        driver: dict[str, Any] = Depends(require_driver),
    ) -> Response:
        start, end, _ = _period_bounds("30dias", start_date, end_date)
        with database_session() as connection:
            rows = report_rows(connection, driver["email"], kind, start, end)
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        if rows:
            headers = list(rows[0].keys())
            writer.writerow(headers)
            for row in rows:
                values = []
                for header in headers:
                    value = row.get(header)
                    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
                        value = "'" + value
                    values.append(value)
                writer.writerow(values)
        else:
            writer.writerow(["sem_dados"])
        content = "\ufeff" + output.getvalue()
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="relatorio-{kind}.csv"'},
        )

    @router.get("/api/driver/reports.pdf")
    def export_pdf(
        kind: ReportKind = "resumo",
        start_date: date | None = Query(default=None, alias="from"),
        end_date: date | None = Query(default=None, alias="to"),
        driver: dict[str, Any] = Depends(require_driver),
    ) -> Response:
        start, end, _ = _period_bounds("30dias", start_date, end_date)
        with database_session() as connection:
            rows = report_rows(connection, driver["email"], kind, start, end)
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
            from xml.sax.saxutils import escape
        except ImportError as exc:
            raise HTTPException(status_code=503, detail="A dependência ReportLab não está instalada.") from exc

        output = io.BytesIO()
        document = SimpleDocTemplate(
            output,
            pagesize=landscape(A4),
            rightMargin=28,
            leftMargin=28,
            topMargin=30,
            bottomMargin=28,
            title="Relatório Veloz Mototáxi",
        )
        styles = getSampleStyleSheet()
        story = [
            Paragraph("Relatório do mototaxista", styles["Title"]),
            Paragraph(
                f"Período: {escape(start.date().isoformat())} a "
                f"{escape((end - timedelta(microseconds=1)).date().isoformat())}",
                styles["Normal"],
            ),
            Paragraph(
                "Valores são armazenados em centavos. Apenas pagamentos confirmados compõem os ganhos; "
                "distância GPS é aproximada e depende de permissão e sinal.",
                styles["BodyText"],
            ),
            Spacer(1, 12),
        ]
        if rows:
            headers = list(rows[0].keys())
            table_data = [[Paragraph(escape(str(value)), styles["BodyText"]) for value in headers]]
            for row in rows[:1000]:
                table_data.append(
                    [Paragraph(escape(str(row.get(header) if row.get(header) is not None else "")), styles["BodyText"])
                     for header in headers]
                )
            table = Table(
                table_data,
                colWidths=[document.width / len(headers)] * len(headers),
                repeatRows=1,
                hAlign="LEFT",
            )
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#183b2c")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#dce4df")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f7f5")]),
                        ("FONTSIZE", (0, 0), (-1, -1), 7),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            story.append(table)
            if len(rows) > 1000:
                story.append(Paragraph("Relatório PDF limitado às primeiras 1.000 linhas.", styles["Italic"]))
        else:
            story.append(Paragraph("Nenhum dado encontrado para o período selecionado.", styles["Normal"]))
        document.build(story)
        return Response(
            content=output.getvalue(),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="relatorio-{kind}.pdf"'},
        )

    return router

