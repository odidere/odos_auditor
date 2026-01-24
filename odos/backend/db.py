import os

import psycopg2
from sqlalchemy import create_engine

from odos.backend.config_loader import CONFIG


def _get_db_creds():
    db_config = CONFIG.get('database', {})
    return {
        "host": os.getenv("POSTGRES_HOST", db_config.get('host', 'localhost')),
        "port": os.getenv("POSTGRES_PORT", db_config.get('port', 5432)),
        "user": os.getenv("POSTGRES_USER", db_config.get('user', 'user')),
        "pass": os.getenv("POSTGRES_PASSWORD", db_config.get('password', 'password')),
        "db": os.getenv("POSTGRES_DB", db_config.get('dbname', 'odos_observability'))
    }


def get_db_engine():
    creds = _get_db_creds()
    url = f"postgresql://{creds['user']}:{creds['pass']}@{creds['host']}:{creds['port']}/{creds['db']}"
    return create_engine(url)


def get_db_connection():
    creds = _get_db_creds()
    return psycopg2.connect(
        host=creds['host'], port=creds['port'],
        user=creds['user'], password=creds['pass'], dbname=creds['db']
    )
