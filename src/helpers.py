import psycopg
from psycopg.rows import namedtuple_row
import os
import logging

connection_string = os.environ["DB_CONNECT_STRING"]


def fetchall(query, args=[]):
    with psycopg.connect(
        conninfo=connection_string, row_factory=namedtuple_row
    ) as conn:
        with conn.cursor() as cur:
            logging.info(f"Query: {query}, Args: {args}")
            cur.execute(query, args)
            return cur.fetchall()


def fetchone(query, args=[]):
    with psycopg.connect(
        conninfo=connection_string, row_factory=namedtuple_row
    ) as conn:
        with conn.cursor() as cur:
            logging.info(f"Query: {query}, Args: {args}")
            cur.execute(query, args)
            result = cur.fetchone()
            return result


def with_psycopg(fn):
    with psycopg.connect(
        conninfo=connection_string, row_factory=namedtuple_row
    ) as conn:
        with conn.cursor() as cur:
            return fn(conn, cur)
