"""CognoDB connection management.

CognoDB speaks Bolt, so the official Neo4j driver works unchanged. One driver
instance is shared for the process lifetime (it owns an internal connection
pool); sessions are short-lived and opened per query.

Every failure mode collapses into DatabaseUnavailable so the web layer has a
single exception type to render as a friendly page.
"""
import logging
from typing import Any

from neo4j import Driver, GraphDatabase
from neo4j.exceptions import Neo4jError

from .config import ConfigError, settings

logger = logging.getLogger(__name__)


class DatabaseUnavailable(RuntimeError):
    """The graph database could not be reached or refused the request."""


_driver: Driver | None = None


def get_driver() -> Driver:
    """Return the shared driver, creating it on first use."""
    global _driver
    if _driver is None:
        settings.validate()
        logger.info("Opening CognoDB driver for %s", settings.uri)
        _driver = GraphDatabase.driver(
            settings.uri,
            auth=(settings.user, settings.password),
            # The free c0 tier allows 200 connections; we stay well under.
            max_connection_pool_size=10,
            connection_timeout=10,
            connection_acquisition_timeout=15,
        )
    return _driver


def close_driver() -> None:
    """Close the shared driver. Called on application shutdown."""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


def check_connection() -> tuple[bool, str]:
    """Cheap health probe used by the status banner, /health and the seed script."""
    try:
        get_driver().verify_connectivity()
        return True, "Connected to CognoDB"
    except ConfigError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001 - a health check must never raise
        logger.warning("CognoDB health check failed: %s", exc)
        return False, f"Cannot reach CognoDB: {exc}"


def run_query(cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Execute a read query and return plain dictionaries.

    Parameters are always handed to the driver separately. No Cypher string in
    this project is ever built by concatenation or f-string interpolation.
    """
    try:
        driver = get_driver()
        with driver.session(database=settings.database) as session:
            result = session.run(cypher, params or {})
            return [record.data() for record in result]

    except ConfigError as exc:
        raise DatabaseUnavailable(str(exc)) from exc

    except Neo4jError as exc:
        # The server was reached but rejected the statement (bad Cypher,
        # constraint violation, unsupported syntax).
        logger.exception("Cypher execution failed")
        raise DatabaseUnavailable(f"The database rejected the query: {exc.message}") from exc

    except Exception as exc:  # noqa: BLE001
        # Everything else - DNS failure, TLS failure, timeout, refused
        # connection - means the same thing to a user: the database is not
        # reachable. The driver signals these with several unrelated exception
        # types (including a bare ValueError for an unresolvable host), so this
        # is deliberately broad rather than an enumerated list.
        logger.warning("CognoDB unreachable: %s", exc)
        raise DatabaseUnavailable(
            "The graph database is currently unreachable. Check that the CognoDB "
            "instance is running and that COGNODB_URI and COGNODB_PASSWORD are correct."
        ) from exc


def run_write(cypher: str, params: dict[str, Any] | None = None) -> None:
    """Execute a write inside a managed transaction (used by the seed script)."""
    try:
        driver = get_driver()
        with driver.session(database=settings.database) as session:
            session.execute_write(lambda tx: tx.run(cypher, params or {}).consume())

    except ConfigError as exc:
        raise DatabaseUnavailable(str(exc)) from exc

    except Neo4jError as exc:
        logger.exception("Write failed")
        raise DatabaseUnavailable(f"Write failed: {exc.message}") from exc

    except Exception as exc:  # noqa: BLE001 - see run_query
        logger.warning("CognoDB unreachable: %s", exc)
        raise DatabaseUnavailable(
            "Cannot write to the database - it is unreachable. Check COGNODB_URI "
            "and COGNODB_PASSWORD in your .env file."
        ) from exc