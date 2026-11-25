import os
import sqlite3
import threading
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
_SCHEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    email TEXT NOT NULL COLLATE NOCASE UNIQUE,
    telefone TEXT NOT NULL,
    idade INTEGER,
    senha_hash TEXT
);
CREATE VIEW IF NOT EXISTS "usuários" AS SELECT * FROM usuarios;
CREATE TABLE IF NOT EXISTS mototaxistas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    email TEXT NOT NULL COLLATE NOCASE UNIQUE,
    telefone TEXT NOT NULL,
    idade INTEGER,
    senha_hash TEXT,
    cpf TEXT,
    cnh TEXT,
    categoria_cnh TEXT,
    validade_cnh TEXT,
    moto TEXT,
    placa TEXT,
    foto_perfil BLOB,
    foto_mime TEXT
);
CREATE TABLE IF NOT EXISTS corridas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    cliente_email TEXT NOT NULL REFERENCES usuarios(email),
    mototaxista_email TEXT REFERENCES mototaxistas(email),
    criada_em TEXT NOT NULL,
    agendada_para TEXT NOT NULL,
    embarque TEXT NOT NULL,
    destino TEXT NOT NULL,
    embarque_lat REAL,
    embarque_lng REAL,
    destino_lat REAL,
    destino_lng REAL,
    passageiro_nome TEXT NOT NULL,
    passageiro_telefone TEXT NOT NULL,
    km_estimados REAL,
    distancia_gps_m INTEGER NOT NULL DEFAULT 0 CHECK (distancia_gps_m >= 0),
    duracao_segundos INTEGER CHECK (duracao_segundos IS NULL OR duracao_segundos >= 0),
    valor_centavos INTEGER NOT NULL CHECK (valor_centavos >= 0),
    forma_pagamento TEXT NOT NULL CHECK (forma_pagamento IN ('Pix', 'Cartão', 'Dinheiro')),
    status TEXT NOT NULL CHECK (status IN ('solicitada', 'aceita', 'em_andamento', 'concluida', 'cancelada')),
    pagamento_status TEXT NOT NULL DEFAULT 'pendente' CHECK (pagamento_status IN ('pendente', 'confirmado')),
    pagamento_confirmado_em TEXT,
    chave_idempotencia TEXT,
    hash_solicitacao TEXT,
    tipo_servico TEXT NOT NULL DEFAULT 'passageiro' CHECK (tipo_servico IN ('passageiro', 'pedido')),
    aceita_em TEXT,
    iniciou_em TEXT,
    finalizada_em TEXT,
    cancelada_em TEXT
);
CREATE INDEX IF NOT EXISTS idx_corridas_driver_date
    ON corridas(mototaxista_email, criada_em);
CREATE INDEX IF NOT EXISTS idx_corridas_status_created
    ON corridas(status, criada_em);
CREATE TABLE IF NOT EXISTS ofertas_corrida (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    corrida_id INTEGER NOT NULL REFERENCES corridas(id) ON DELETE CASCADE,
    mototaxista_email TEXT NOT NULL REFERENCES mototaxistas(email) ON DELETE CASCADE,
    oferecida_em TEXT NOT NULL,
    resposta TEXT NOT NULL DEFAULT 'pendente'
        CHECK (resposta IN ('pendente', 'aceita', 'recusada', 'expirada')),
    respondida_em TEXT,
    UNIQUE (corrida_id, mototaxista_email)
);
CREATE INDEX IF NOT EXISTS idx_ofertas_driver_status
    ON ofertas_corrida(mototaxista_email, resposta);
CREATE TABLE IF NOT EXISTS disponibilidade_mototaxista (
    mototaxista_email TEXT PRIMARY KEY REFERENCES mototaxistas(email) ON DELETE CASCADE,
    online INTEGER NOT NULL DEFAULT 0 CHECK (online IN (0, 1)),
    alterada_em TEXT NOT NULL,
    last_seen_em TEXT
);
CREATE TABLE IF NOT EXISTS eventos_disponibilidade (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mototaxista_email TEXT NOT NULL REFERENCES mototaxistas(email) ON DELETE CASCADE,
    online INTEGER NOT NULL CHECK (online IN (0, 1)),
    registrada_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_disponibilidade_driver_date
    ON eventos_disponibilidade(mototaxista_email, registrada_em);
CREATE TABLE IF NOT EXISTS despesas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mototaxista_email TEXT NOT NULL REFERENCES mototaxistas(email) ON DELETE CASCADE,
    categoria TEXT NOT NULL
        CHECK (categoria IN ('Combustível', 'Manutenção', 'Troca de óleo', 'Pneus', 'Estacionamento', 'Outras despesas')),
    descricao TEXT NOT NULL,
    valor_centavos INTEGER NOT NULL CHECK (valor_centavos > 0),
    data_despesa TEXT NOT NULL,
    criada_em TEXT NOT NULL,
    atualizada_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_despesas_driver_date
    ON despesas(mototaxista_email, data_despesa);
CREATE TABLE IF NOT EXISTS metas_mototaxista (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mototaxista_email TEXT NOT NULL REFERENCES mototaxistas(email) ON DELETE CASCADE,
    periodo TEXT NOT NULL CHECK (periodo IN ('diaria', 'semanal', 'mensal')),
    meta_centavos INTEGER CHECK (meta_centavos IS NULL OR meta_centavos >= 0),
    meta_corridas INTEGER CHECK (meta_corridas IS NULL OR meta_corridas >= 0),
    atualizada_em TEXT NOT NULL,
    UNIQUE (mototaxista_email, periodo)
);
CREATE TABLE IF NOT EXISTS notificacoes_mototaxista (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mototaxista_email TEXT NOT NULL REFERENCES mototaxistas(email) ON DELETE CASCADE,
    tipo TEXT NOT NULL,
    titulo TEXT NOT NULL,
    mensagem TEXT NOT NULL,
    criada_em TEXT NOT NULL,
    lida_em TEXT
);
CREATE INDEX IF NOT EXISTS idx_notificacoes_driver_date
    ON notificacoes_mototaxista(mototaxista_email, criada_em);
CREATE TABLE IF NOT EXISTS pontos_gps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    corrida_id INTEGER NOT NULL REFERENCES corridas(id) ON DELETE CASCADE,
    mototaxista_email TEXT NOT NULL REFERENCES mototaxistas(email) ON DELETE CASCADE,
    latitude REAL NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude REAL NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    precisao_m REAL NOT NULL CHECK (precisao_m >= 0 AND precisao_m <= 100),
    registrada_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pontos_gps_ride_date
    ON pontos_gps(corrida_id, registrada_em);
CREATE TABLE IF NOT EXISTS avaliacoes_corrida (
    corrida_id INTEGER PRIMARY KEY REFERENCES corridas(id) ON DELETE CASCADE,
    mototaxista_email TEXT NOT NULL REFERENCES mototaxistas(email) ON DELETE CASCADE,
    estrelas INTEGER NOT NULL CHECK (estrelas BETWEEN 1 AND 5),
    comentario TEXT,
    autorizada INTEGER NOT NULL DEFAULT 0 CHECK (autorizada IN (0, 1)),
    criada_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_avaliacoes_driver_date
    ON avaliacoes_corrida(mototaxista_email, criada_em);
CREATE TABLE IF NOT EXISTS entregas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    cliente_email TEXT NOT NULL REFERENCES usuarios(email),
    mototaxista_email TEXT REFERENCES mototaxistas(email),
    criada_em TEXT NOT NULL,
    retirada_endereco TEXT NOT NULL,
    retirada_numero TEXT NOT NULL,
    retirada_complemento TEXT NOT NULL DEFAULT '',
    retirada_referencia TEXT NOT NULL DEFAULT '',
    retirada_lat REAL NOT NULL,
    retirada_lng REAL NOT NULL,
    remetente_nome TEXT NOT NULL,
    remetente_telefone TEXT NOT NULL,
    destino_endereco TEXT NOT NULL,
    destino_numero TEXT NOT NULL,
    destino_complemento TEXT NOT NULL DEFAULT '',
    destino_referencia TEXT NOT NULL DEFAULT '',
    destino_lat REAL NOT NULL,
    destino_lng REAL NOT NULL,
    destinatario_nome TEXT NOT NULL,
    destinatario_telefone TEXT NOT NULL,
    instrucoes_entrega TEXT NOT NULL DEFAULT '',
    categoria TEXT NOT NULL,
    descricao TEXT NOT NULL,
    quantidade_volumes INTEGER NOT NULL CHECK (quantidade_volumes BETWEEN 1 AND 10),
    peso_kg REAL NOT NULL CHECK (peso_kg > 0),
    comprimento_cm REAL NOT NULL CHECK (comprimento_cm > 0),
    largura_cm REAL NOT NULL CHECK (largura_cm > 0),
    altura_cm REAL NOT NULL CHECK (altura_cm > 0),
    fragil INTEGER NOT NULL CHECK (fragil IN (0, 1)),
    observacoes TEXT NOT NULL DEFAULT '',
    foto BLOB,
    foto_mime TEXT,
    distancia_m INTEGER NOT NULL CHECK (distancia_m > 0),
    duracao_estimado_segundos INTEGER NOT NULL CHECK (duracao_estimado_segundos > 0),
    valor_centavos INTEGER NOT NULL CHECK (valor_centavos > 0),
    forma_pagamento TEXT NOT NULL CHECK (forma_pagamento = 'Dinheiro'),
    pagamento_status TEXT NOT NULL DEFAULT 'pendente'
        CHECK (pagamento_status IN ('pendente', 'confirmado')),
    status TEXT NOT NULL CHECK (status IN (
        'solicitada', 'aceita', 'a_caminho_retirada', 'chegada_retirada',
        'coletado', 'em_transito', 'chegada_destino', 'entregue',
        'cancelada', 'problema'
    )),
    codigo_salt BLOB NOT NULL,
    codigo_hash BLOB NOT NULL,
    tentativas_codigo INTEGER NOT NULL DEFAULT 0 CHECK (tentativas_codigo BETWEEN 0 AND 5),
    codigo_bloqueado INTEGER NOT NULL DEFAULT 0 CHECK (codigo_bloqueado IN (0, 1)),
    codigo_geracoes INTEGER NOT NULL DEFAULT 1 CHECK (codigo_geracoes BETWEEN 1 AND 5),
    aceita_em TEXT,
    coletado_em TEXT,
    entregue_em TEXT,
    cancelada_em TEXT,
    comprovante_entrega TEXT,
    problema_tipo TEXT,
    problema_descricao TEXT,
    chave_idempotencia TEXT NOT NULL UNIQUE,
    hash_solicitacao TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entregas_driver_status
    ON entregas(mototaxista_email, status, criada_em);
CREATE INDEX IF NOT EXISTS idx_entregas_customer_date
    ON entregas(cliente_email, criada_em);
CREATE INDEX IF NOT EXISTS idx_entregas_status_date
    ON entregas(status, criada_em);
CREATE TABLE IF NOT EXISTS ofertas_entrega (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entrega_id INTEGER NOT NULL REFERENCES entregas(id) ON DELETE CASCADE,
    mototaxista_email TEXT NOT NULL REFERENCES mototaxistas(email) ON DELETE CASCADE,
    oferecida_em TEXT NOT NULL,
    resposta TEXT NOT NULL DEFAULT 'pendente'
        CHECK (resposta IN ('pendente', 'aceita', 'recusada', 'expirada')),
    respondida_em TEXT,
    UNIQUE (entrega_id, mototaxista_email)
);
CREATE INDEX IF NOT EXISTS idx_ofertas_entrega_driver_status
    ON ofertas_entrega(mototaxista_email, resposta);
CREATE TABLE IF NOT EXISTS status_entrega (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entrega_id INTEGER NOT NULL REFERENCES entregas(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    alterado_por TEXT NOT NULL,
    motivo TEXT NOT NULL DEFAULT '',
    registrado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_status_entrega_date
    ON status_entrega(entrega_id, registrado_em);
CREATE TABLE IF NOT EXISTS pontos_gps_entrega (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entrega_id INTEGER NOT NULL REFERENCES entregas(id) ON DELETE CASCADE,
    mototaxista_email TEXT NOT NULL REFERENCES mototaxistas(email) ON DELETE CASCADE,
    latitude REAL NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude REAL NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    precisao_m REAL NOT NULL CHECK (precisao_m BETWEEN 0 AND 100),
    registrada_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pontos_gps_entrega_date
    ON pontos_gps_entrega(entrega_id, registrada_em);
CREATE TABLE IF NOT EXISTS habilitacao_entregas (
    mototaxista_email TEXT PRIMARY KEY REFERENCES mototaxistas(email) ON DELETE CASCADE,
    habilitado INTEGER NOT NULL DEFAULT 0 CHECK (habilitado IN (0, 1)),
    alterado_por TEXT NOT NULL,
    alterado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS configuracao_entregas (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL,
    alterado_por TEXT NOT NULL,
    alterado_em TEXT NOT NULL
);
"""
_INITIALIZED_DATABASES: set[str] = set()
_SCHEMA_LOCK = threading.Lock()


def _dict_row(cursor: sqlite3.Cursor, row: tuple[object, ...]) -> dict[str, object]:
    return {
        column[0]: row[index]
        for index, column in enumerate(cursor.description or ())
    }


def _connect_sqlite() -> sqlite3.Connection:
    database_path = os.environ.get(
        "VELOZ_SQLITE_PATH",
        str(BASE_DIR / "veloz.sqlite3"),
    )
    if database_path != ":memory:":
        path = Path(database_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        database_path = str(path.resolve())

    connection = sqlite3.connect(database_path, timeout=10)
    connection.row_factory = _dict_row
    connection.execute("PRAGMA foreign_keys = ON")

    if database_path == ":memory:":
        connection.executescript(_SCHEMA)
        _migrate_sqlite(connection)
    elif database_path not in _INITIALIZED_DATABASES:
        with _SCHEMA_LOCK:
            if database_path not in _INITIALIZED_DATABASES:
                try:
                    connection.executescript(_SCHEMA)
                    _migrate_sqlite(connection)
                except sqlite3.Error:
                    connection.close()
                    raise
                _INITIALIZED_DATABASES.add(database_path)

    return connection


def _migrate_sqlite(connection: sqlite3.Connection) -> None:
    table_names = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "usuários" in table_names and "usuarios" not in table_names:
        connection.execute('ALTER TABLE "usuários" RENAME TO usuarios')
        connection.execute('CREATE VIEW IF NOT EXISTS "usuários" AS SELECT * FROM usuarios')

    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(corridas)").fetchall()
    }
    if "passageiro_nome" not in columns:
        connection.execute(
            "ALTER TABLE corridas ADD COLUMN passageiro_nome TEXT NOT NULL DEFAULT ''"
        )
    if "passageiro_telefone" not in columns:
        connection.execute(
            "ALTER TABLE corridas ADD COLUMN passageiro_telefone TEXT NOT NULL DEFAULT ''"
        )
    for column in ("embarque_lat", "embarque_lng", "destino_lat", "destino_lng"):
        if column not in columns:
            connection.execute(f"ALTER TABLE corridas ADD COLUMN {column} REAL")
    if "chave_idempotencia" not in columns:
        connection.execute("ALTER TABLE corridas ADD COLUMN chave_idempotencia TEXT")
    if "hash_solicitacao" not in columns:
        connection.execute("ALTER TABLE corridas ADD COLUMN hash_solicitacao TEXT")
    if "tipo_servico" not in columns:
        connection.execute(
            "ALTER TABLE corridas ADD COLUMN tipo_servico TEXT NOT NULL DEFAULT 'passageiro'"
        )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_corridas_idempotencia "
        "ON corridas(chave_idempotencia)"
    )
    driver_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(mototaxistas)").fetchall()
    }
    if "foto_perfil" not in driver_columns:
        connection.execute("ALTER TABLE mototaxistas ADD COLUMN foto_perfil BLOB")
    if "foto_mime" not in driver_columns:
        connection.execute("ALTER TABLE mototaxistas ADD COLUMN foto_mime TEXT")
    availability_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(disponibilidade_mototaxista)").fetchall()
    }
    if "last_seen_em" not in availability_columns:
        connection.execute("ALTER TABLE disponibilidade_mototaxista ADD COLUMN last_seen_em TEXT")
    delivery_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(entregas)").fetchall()
    }
    if "codigo_geracoes" not in delivery_columns:
        connection.execute(
            "ALTER TABLE entregas ADD COLUMN codigo_geracoes INTEGER NOT NULL DEFAULT 1"
        )


def _connect_mysql():
    import pymysql

    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", ""),
        database=os.environ.get("MYSQL_DATABASE", "mototaxi"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def connect_database(backend: str | None = None):
    selected_backend = (
        backend or os.environ.get("VELOZ_DATABASE_BACKEND", "sqlite")
    ).lower()
    if selected_backend == "sqlite":
        return _connect_sqlite()
    if selected_backend == "mysql":
        return _connect_mysql()
    raise ValueError(f"Backend de banco não suportado: {selected_backend}")
