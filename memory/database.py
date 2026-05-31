"""
memory/database.py — Client REST léger pour Supabase (PostgREST).

Pourquoi pas le SDK officiel `supabase` : sur Python 3.14 il tire des
dépendances natives (pyiceberg via storage3) qui ne compilent pas. On utilise
donc directement l'API REST PostgREST avec `requests` — léger, robuste, idéal
pour un déploiement serverless.

L'interface imite le SDK Supabase pour rester familière :
    database.table("trading_signals").select("*").eq("ticker", "PLTR").execute().data
    database.table("trading_signals").insert({...}).execute().data
    database.table("trading_signals").update({...}).eq("id", x).execute()

Aucune suppression n'est exposée (règle métier : on n'efface jamais).
"""

import logging

import requests

import config

logger = logging.getLogger("database")


class QueryResult:
    """Résultat d'une requête : .data contient la liste de lignes."""
    def __init__(self, data):
        self.data = data if data is not None else []


class Query:
    """Constructeur de requête PostgREST (sous-ensemble du SDK Supabase)."""

    def __init__(self, base_url: str, headers: dict, table_name: str):
        self._base = base_url
        self._headers = headers
        self._table = table_name
        self._method = "GET"
        self._params: list[tuple[str, str]] = []
        self._body = None
        self._timeout = config.DATA_SOURCE["request_timeout"]

    # — sélection / écriture —
    def select(self, columns: str = "*"):
        self._method = "GET"
        self._params.append(("select", columns.replace(" ", "")))
        return self

    def insert(self, payload):
        self._method = "POST"
        self._body = payload
        return self

    def update(self, payload: dict):
        self._method = "PATCH"
        self._body = payload
        return self

    # — filtres —
    def eq(self, col, val):  return self._filter(col, "eq", val)
    def neq(self, col, val): return self._filter(col, "neq", val)
    def gt(self, col, val):  return self._filter(col, "gt", val)
    def gte(self, col, val): return self._filter(col, "gte", val)
    def lt(self, col, val):  return self._filter(col, "lt", val)
    def lte(self, col, val): return self._filter(col, "lte", val)

    def is_(self, col, val):
        return self._filter(col, "is", val)

    def _filter(self, col, op, val):
        if isinstance(val, bool):
            val = "true" if val else "false"
        self._params.append((col, f"{op}.{val}"))
        return self

    # — tri / limite —
    def order(self, col, desc: bool = False):
        self._params.append(("order", f"{col}.{'desc' if desc else 'asc'}"))
        return self

    def limit(self, n: int):
        self._params.append(("limit", str(n)))
        return self

    # — exécution —
    def execute(self) -> QueryResult:
        url = f"{self._base}/{self._table}"
        headers = dict(self._headers)
        if self._method in ("POST", "PATCH"):
            headers["Prefer"] = "return=representation"

        resp = requests.request(
            self._method, url,
            headers=headers,
            params=self._params,
            json=self._body if self._body is not None else None,
            timeout=self._timeout,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Supabase {resp.status_code}: {resp.text[:300]}")

        try:
            data = resp.json()
        except ValueError:
            data = []
        return QueryResult(data)


class SupabaseREST:
    def __init__(self, url: str, service_key: str):
        self.base_url = url.rstrip("/") + "/rest/v1"
        self.headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        }

    def table(self, name: str) -> Query:
        return Query(self.base_url, self.headers, name)


_client: SupabaseREST | None = None


def get_client() -> SupabaseREST:
    global _client
    if _client is not None:
        return _client
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY manquants dans .env")
    _client = SupabaseREST(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
    logger.info("Client Supabase REST initialisé.")
    return _client


def table(name: str) -> Query:
    return get_client().table(name)


def ping() -> bool:
    try:
        get_client().table("trading_signals").select("id").limit(1).execute()
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("Ping Supabase échoué : %s", e)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Connexion :", "OK" if ping() else "ÉCHEC")
