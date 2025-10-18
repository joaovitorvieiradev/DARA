import re
import unicodedata
import traceback
from typing import List, Dict, Any, Tuple
from datetime import datetime, date 
from operacoes.db_reader import get_db_connection
from typing import Tuple, List, Dict, Any
# =========================================================
# 1. FUNÇÕES AUXILIARES, UTILITÁRIOS E MAPAS
# =========================================================

MONTH_NAME_TO_NUMBER_MAP = {
    "janeiro": 1, "jan": 1,
    "fevereiro": 2, "fev": 2,
    "marco": 3, "março": 3, "mar": 3,
    "abril": 4, "abr": 4,
    "maio": 5, "mai": 5,
    "junho": 6, "jun": 6,
    "julho": 7, "jul": 7,
    "agosto": 8, "ago": 8,
    "setembro": 9, "set": 9,
    "outubro": 10, "out": 10,
    "novembro": 11, "nov": 11,
    "dezembro": 12, "dez": 12
}

RESORT_CODES = ['resort_alpha', 'resort_beta', 'resort_gamma', 'resort_delta', 'resort_epsilon', 'all_resorts']

COLUMN_NAME_MAP_FEEDBACK = {
    "id": "id", "hotel": "resort_code", "fonteavaliacao": "source", "datapreenchimento": "submission_date",
    "datacheckin": "checkin_date", "datacheckout": "checkout_date", "room": "room_number", "motivoviagem": "reason_for_travel",
    "cr": "cost_center", "palavrachave": "keyword", "nota": "score", "tipocomentario": "feedback_type",
    "comentario": "comment", "nreclamacoes": "complaint_count", "chcek": "check", "chave": "key", "predio": "building",
    "dia": "day", "semana": "week", "mes": "month", "ano": "year", "anomes": "year_month", "notaajuste": "adjusted_score",
    "notapadronizada": "standardized_score", "npsscore": "nps_score", "nhospedes": "guest_count", "rn": "rn", "periodo": "period"
}

def _format_column_name(column_name: str, name_map: dict) -> str:
    name_lower = column_name.lower()
    if name_map and name_lower in name_map:
        return name_map[name_lower]
    nfkd_form = unicodedata.normalize('NFD', column_name)
    no_accents = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    return no_accents.lower().replace(' ', '_').replace('-', '_')

def _g(filtros: dict) -> dict:
    """Normaliza e aplica aliases a um dicionário de filtros."""
    def _norm_key(s: str) -> str:
        s = (s or "").strip().lower()
        s = unicodedata.normalize("NFKD", s)
        s = "".join(c for c in s if not unicodedata.combining(c))
        return re.sub(r"[\s_]+", "", s)
    f_normalizado = {_norm_key(k): v for k, v in (filtros or {}).items()}
    alias = {
        "resort": "hotel", "unit": "hotel",
        "month": "mes", "period": "mes", "year": "ano",
        "building": "predio", "feedbacktype": "tipocomentario",
        "keyword": "palavrachave", "specifickeyword": "palavrachave"
    }
    out = {}
    for k, v in f_normalizado.items():
        canonical_key = alias.get(k, k)
        out[canonical_key] = v
    return out

def _normalize_resort_code(resort_value: Any) -> Any:
    """Retorna o código canônico do resort se encontrado no input."""
    if not isinstance(resort_value, str):
        return resort_value
    try:
        norm_valor = resort_value.lower()
        norm_valor = (norm_valor
                      .replace('á', 'a').replace('à', 'a').replace('ã', 'a').replace('â', 'a')
                      .replace('é', 'e').replace('ê', 'e')
                      .replace('ç', 'c'))
        for canonical in RESORT_CODES:
            if canonical in norm_valor:
                return canonical
        return resort_value
    except Exception:
        return resort_value

def _translate_period_to_number(period_value: Any) -> Any:
    """Tenta converter um nome de mês (str) para seu número (int)."""
    if not isinstance(period_value, str):
        return period_value
    try:
        normalized_key = period_value.lower().strip().replace('ç', 'c')
        translated_value = MONTH_NAME_TO_NUMBER_MAP.get(normalized_key)
        if translated_value is not None:
            return translated_value
        return int(normalized_key)
    except (ValueError, TypeError, AttributeError):
        return period_value

def _build_flexible_where_clause(
    where_clauses: list, params: list, norm_filters: dict, filter_key: str, db_column_name: str
):
    """Adiciona cláusula WHERE flexível, normalizando nomes de hotel se necessário."""
    value = (norm_filters or {}).get(filter_key)
    if filter_key.lower() == 'hotel':
        value = _normalize_resort_code(value)
    if value and value != 'all_resorts':
        where_clauses.append(f'unaccent(lower({db_column_name})) = unaccent(lower(%s))')
        params.append(value)


# ========================
# Module Constants
# ========================
TABLE_GUEST_FEEDBACK = "guest_feedback"


def _to_iso_date(d) -> str | None:
    """Converte date/datetime/str/None para 'YYYY-MM-DD' (ou None)."""
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date().isoformat()
    if isinstance(d, date):
        return d.isoformat()
    return str(d)[:10]

def _get_latest_date(conn, table: str, where_sql: str, params: list, date_column: str = "datapreenchimento"):
    """Retorna MAX(date_column) respeitando o mesmo WHERE/params."""
    with conn.cursor() as cur_aux:
        query_max = f'SELECT MAX({date_column}) FROM "{table}" {where_sql}'
        cur_aux.execute(query_max, tuple(params))
        return cur_aux.fetchone()[0]


def _execute_standard_query(config: dict, filtros: dict, limit: int, offset: int) -> Tuple[List[Dict[str, Any]], int]:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        norm_filters = _g(filtros or {})

        table = config["tabela"]
        flexible_filters = config.get("filtros_flexiveis", {})
        exact_filters = config.get("filtros_exatos", {})
        desired_columns = config.get("colunas_desejadas", "*")
        default_order = config.get("ordenacao_padrao", "1")

        where_clauses, params = [], []

        for api_key, col_name in (flexible_filters or {}).items():
            _build_flexible_where_clause(where_clauses, params, norm_filters, api_key, col_name)

        for api_key, col_name in (exact_filters or {}).items():
            value = norm_filters.get(api_key)
            if api_key.lower() == 'mes':
                value = _translate_period_to_number(value)
            if value is not None and value != '':
                where_clauses.append(f'{col_name} = %s')
                params.append(value)

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        data_until_raw = _get_latest_date(conn, table, where_sql, params, date_column="datapreenchimento")
        data_until = _to_iso_date(data_until_raw)

        count_query = f'SELECT COUNT(*) FROM "{table}" {where_sql}'
        cur.execute(count_query, tuple(params))
        total_records = cur.fetchone()[0]

        query = f'SELECT {desired_columns} FROM "{table}" {where_sql} ORDER BY {default_order} LIMIT %s OFFSET %s'
        cur.execute(query, tuple(params + [limit, offset]))

        columns = [_format_column_name(d[0], COLUMN_NAME_MAP_FEEDBACK) for d in cur.description]
        data = [dict(zip(columns, row)) for row in cur.fetchall()]

        if data_until:
            for d in data:
                d["data_until"] = data_until

        return data, total_records

    finally:
        if conn:
            conn.close()

# ===========================
# 3. PUBLIC API FUNCTIONS
# ===========================

def list_guest_feedback(filtros: dict, limit: int, offset: int) -> Tuple[List[dict], int]:
    """
    Busca e lista os registros de comentários e reclamações dos hóspedes. Retorna o texto do comentário, data, hotel, tipo, etc. Use esta ferramenta para obter uma lista de reclamações brutas com base em filtros.
    """
    query_config = {
        "tabela": TABLE_GUEST_FEEDBACK,
        "colunas_desejadas": "datapreenchimento, hotel, cr, predio, tipocomentario, palavrachave, nota, comentario, ano, mes, dia",
        "filtros_flexiveis": {
            "hotel": "hotel", 
            "tipocomentario": "tipocomentario",
            "palavrachave": "palavrachave",
            "cr": "cr",
            "predio": "predio"
        },
        "filtros_exatos": {
            "ano": "ano",
            "mes": "mes", 
            "dia": "dia"
        },
        "ordenacao_padrao": "datapreenchimento DESC"
    }
    return _execute_standard_query(query_config, filtros, limit, offset)

def count_feedback_by_type(filtros: dict, limit: int, offset: int) -> Tuple[List[dict], int, str | None]:
    """
    Conta e agrupa o total de comentários por tipo (Reclamação, Elogio, Sugestão).
    Retorna a contagem para cada tipo em um determinado período.
    """
    f = _g(filtros)

    hotel_input = f.get("hotel")
    month_input = f.get("mes")
    year = f.get("ano")

    hotel = _normalize_resort_code(hotel_input)
    month = _translate_period_to_number(month_input)

    if not all([hotel, year, month]):
        raise ValueError("Filtros 'hotel', 'ano' e 'mes' são obrigatórios.")

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        where_clauses, params = [], []
        _build_flexible_where_clause(where_clauses, params, {"hotel": hotel}, "hotel", "hotel")
        _build_flexible_where_clause(where_clauses, params, f, "predio", "predio")
        _build_flexible_where_clause(where_clauses, params, f, "cr", "cr")
        where_clauses.extend(["ano = %s", "mes = %s"])
        params.extend([int(year), int(month)])
        where_sql = "WHERE " + " AND ".join(where_clauses)

        data_until_raw = _get_latest_date(conn, TABLE_GUEST_FEEDBACK, where_sql, params, "datapreenchimento")
        data_until = _to_iso_date(data_until_raw)

        cur.execute(
            f"SELECT COUNT(DISTINCT tipocomentario) FROM {TABLE_GUEST_FEEDBACK} {where_sql}",
            tuple(params)
        )
        total_records = cur.fetchone()[0] or 0

        query = f"""
            SELECT tipocomentario, COUNT(*) AS total
            FROM {TABLE_GUEST_FEEDBACK}
            {where_sql}
            GROUP BY tipocomentario
            ORDER BY total DESC
            LIMIT %s OFFSET %s
        """
        cur.execute(query, tuple(params + [limit, offset]))
        columns = [_format_column_name(d[0], COLUMN_NAME_MAP_FEEDBACK) for d in cur.description]
        data = [dict(zip(columns, row)) for row in cur.fetchall()]

        return data, total_records, data_until

    finally:
        if conn:
            conn.close()

def rank_by_keyword(filtros: dict, limit: int, offset: int) -> Tuple[List[dict], int, str | None]:
    """
    Analisa os textos das reclamações e ranqueia as palavras-chave mais citadas.
    """
    f = _g(filtros)

    year = f.get("ano")
    month_input = f.get("mes")
    month = _translate_period_to_number(month_input)
    hotel_required = f.get("hotel")

    if not all([hotel_required, year, month]):
        raise ValueError("Filtros 'hotel', 'ano' e 'mes' são obrigatórios.")

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        where_clauses, params = [], []
        _build_flexible_where_clause(where_clauses, params, f, "hotel", "hotel")
        _build_flexible_where_clause(where_clauses, params, f, "tipocomentario", "tipocomentario")
        _build_flexible_where_clause(where_clauses, params, f, "cr", "cr")
        _build_flexible_where_clause(where_clauses, params, f, "predio", "predio")
        where_clauses.extend(["ano = %s", "mes = %s"])
        params.extend([int(year), int(month)])

        where_sql = "WHERE " + " AND ".join(where_clauses)

        only_rank_where_sql = where_sql + " AND palavrachave IS NOT NULL AND palavrachave <> ''"

        data_until_raw = _get_latest_date(conn, TABLE_GUEST_FEEDBACK, only_rank_where_sql, params, "datapreenchimento")
        data_until = _to_iso_date(data_until_raw)

        cur.execute(
            f"SELECT COUNT(DISTINCT palavrachave) FROM {TABLE_GUEST_FEEDBACK} {only_rank_where_sql}",
            tuple(params)
        )
        total_records = cur.fetchone()[0] or 0

        query = f"""
            SELECT palavrachave, COUNT(*) AS total
            FROM {TABLE_GUEST_FEEDBACK}
            {only_rank_where_sql}
            GROUP BY palavrachave
            ORDER BY total DESC
            LIMIT %s OFFSET %s
        """
        cur.execute(query, tuple(params + [limit, offset]))

        columns = [_format_column_name(d[0], COLUMN_NAME_MAP_FEEDBACK) for d in cur.description]
        data = [dict(zip(columns, row)) for row in cur.fetchall()]

        return data, total_records, data_until

    finally:
        if conn:
            conn.close()

def search_feedback_by_keyword(filtros: dict, limit: int, offset: int) -> Tuple[List[Dict[str, Any]], int, str | None]:
    """
    Busca comentários pela PALAVRA-CHAVE classificada (match exato em `palavrachave`).
    """
    f = _g(filtros)
    year = f.get("ano")
    month_input = f.get("mes")
    hotel_required = f.get("hotel")
    exact_term = f.get("palavrachave")

    month = _translate_period_to_number(month_input)

    if not all([hotel_required, year, month, exact_term]):
        raise ValueError("Filtros 'hotel', 'ano', 'mes' e 'palavrachave' são obrigatórios.")

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        where_clauses, params = [], []

        _build_flexible_where_clause(where_clauses, params, f, "hotel", "hotel")
        _build_flexible_where_clause(where_clauses, params, f, "tipocomentario", "tipocomentario")
        _build_flexible_where_clause(where_clauses, params, f, "cr", "cr")
        _build_flexible_where_clause(where_clauses, params, f, "predio", "predio")

        where_clauses.extend(["ano = %s", "mes = %s"])
        params.extend([int(year), int(month)])

        where_clauses.append("unaccent(lower(palavrachave)) = unaccent(lower(%s))")
        params.append(exact_term)

        where_sql = "WHERE " + " AND ".join(where_clauses)

        data_until_raw = _get_latest_date(conn, TABLE_GUEST_FEEDBACK, where_sql, params, "datapreenchimento")
        data_until = _to_iso_date(data_until_raw)

        cur.execute(f"SELECT COUNT(*) FROM {TABLE_GUEST_FEEDBACK} {where_sql}", tuple(params))
        total_records = cur.fetchone()[0] or 0

        desired_columns = (
            "datapreenchimento, hotel, cr, predio, tipocomentario, nota, comentario, palavrachave, ano, mes"
        )
        query = f"""
            SELECT {desired_columns}
            FROM {TABLE_GUEST_FEEDBACK}
            {where_sql}
            ORDER BY datapreenchimento DESC
            LIMIT %s OFFSET %s
        """
        cur.execute(query, tuple(params + [limit, offset]))

        columns = [_format_column_name(d[0], COLUMN_NAME_MAP_FEEDBACK) for d in cur.description]
        data = [dict(zip(columns, row)) for row in cur.fetchall()]

        return data, total_records, data_until

    finally:
        if conn:
            conn.close()
