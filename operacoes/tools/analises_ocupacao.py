import traceback
import unicodedata
from typing import List, Dict, Any, Tuple
from operacoes.db_reader import get_db_connection

# =========================================================
# 1. CONSTANTES E MAPAS
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

RESORT_CODES = ['resort_alpha', 'resort_beta', 'resort_gamma', 'resort_delta', 'resort_epsilon']

COLUMN_NAME_MAP_OCCUPANCY = {
    "id": "id",
    "resort": "resort_code",
    "empresa": "company",
    "data": "date",
    "hosptotal": "total_guests",
    "lazer": "leisure_guests",
    "eventos": "events_guests",
    "mes": "month",
    "ano": "year",
    "dia": "day",
    "chavehospedes": "guest_key"
}

def _format_column_name(column_name: str, name_map: dict) -> str:
    name_lower = column_name.lower()
    if name_lower in name_map:
        return name_map[name_lower]
    nfkd_form = unicodedata.normalize('NFD', column_name)
    no_accents = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    return no_accents.lower().replace(' ', '_').replace('-', '_')

def _g(filtros: dict, *keys: str):
    for k in keys:
        if k in filtros: return filtros.get(k)
        lk = k.lower()
        if lk in filtros: return filtros.get(lk)
        uk = k.upper()
        if uk in filtros: return filtros.get(uk)
        ck = k.capitalize()
        if ck in filtros: return filtros.get(ck)
    return None

def _normalize_resort_code(resort_value: Any) -> Any:
    if not isinstance(resort_value, str):
        return resort_value 

    try:
        norm_valor = resort_value.lower()
        norm_valor = norm_valor.replace('á', 'a').replace('à', 'a').replace('ã', 'a').replace('â', 'a')
        norm_valor = norm_valor.replace('é', 'e').replace('ê', 'e')
        norm_valor = norm_valor.replace('ç', 'c')
        
        for canonical in RESORT_CODES:
            if canonical in norm_valor:
                return canonical 

        return resort_value
    except Exception:
        return resort_value

def _build_flexible_where_clause(
    where_clauses: list, params: list, filtros: dict, filter_key: str, db_column_name: str
):
    value = _g(filtros, filter_key)
    
    if db_column_name.lower() in ('hotel', 'resort'):
        value = _normalize_resort_code(value)

    if value:
        where_clauses.append(f'unaccent(lower({db_column_name})) = unaccent(lower(%s))')
        params.append(value)


def _get_latest_date(conn, table: str, where_sql: str, params: list, date_column: str) -> str:
    cur = conn.cursor()
    query = f"""
        SELECT MAX({date_column})
        FROM "{table}"
        {where_sql}
    """
    cur.execute(query, tuple(params))
    result = cur.fetchone()
    if result and result[0]:
        value = result[0]

        if hasattr(value, "strftime"):
            return value.strftime("%d/%m/%Y")

        if isinstance(value, str):
            return value

        return str(value)
    return None


def _translate_period_to_number(period_value: Any) -> Any:
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

# =======================
# Módulo de Constantes
# =======================
TABLE_DAILY_OCCUPANCY = "daily_occupancy"
TABLE_GUEST_FEEDBACK = "guest_feedback"
TABLE_DEPARTMENT_COMPLAINT_TARGETS = "department_complaint_targets"

# ========================
# 2. CONSULTAS PADRÃO
# ========================

def _execute_standard_query(config: dict, filtros: dict, limit: int, offset: int) -> Tuple[List[Dict[str, Any]], int, Any]:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        table = config["tabela"]
        flexible_filters = config.get("filtros_flexiveis", {})
        exact_filters = config.get("filtros_exatos", {})
        desired_columns = config.get("colunas_desejadas", "*")
        default_order = config.get("ordenacao_padrao", "1")

        where_clauses, params = [], []
        used_keys = set()
        
        for api_key, col_name in flexible_filters.items():
            if _g(filtros, api_key) and col_name not in used_keys:
                _build_flexible_where_clause(where_clauses, params, filtros, api_key, col_name)
                used_keys.add(col_name)

        for api_key, col_name in exact_filters.items():
            value = _g(filtros, api_key)
            
            if api_key.lower() in ('mes', 'periodo'):
                value = _translate_period_to_number(value)
            
            if value is not None:
                where_clauses.append(f'{col_name} = %s')
                params.append(value)
        
        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        
        count_query = f'SELECT COUNT(*) FROM "{table}" {where_sql}'
        cur.execute(count_query, tuple(params))
        total_records = cur.fetchone()
        total_records = total_records[0] if total_records else 0

        cur.execute(f'SELECT MAX(data) FROM "{table}" {where_sql}', tuple(params))
        data_until_raw = cur.fetchone()
        data_until = None 

        if data_until_raw and data_until_raw[0]:
            value = data_until_raw[0]
            if hasattr(value, "strftime"):
                data_until = value.strftime("%d/%m/%Y")
            else:
                data_until = str(value)

        query = f'SELECT {desired_columns} FROM "{table}" {where_sql} ORDER BY {default_order} LIMIT %s OFFSET %s'
        cur.execute(query, tuple(params + [limit, offset]))
        
        columns = [_format_column_name(desc[0], COLUMN_NAME_MAP_OCCUPANCY) for desc in cur.description]
        data = [dict(zip(columns, row)) for row in cur.fetchall()]
        
        return data, total_records, data_until
    finally:
        if conn: conn.close()

# ========================
# 3. FERRAMENTAS FINAIS
# ========================

def list_daily_occupancy(filtros: dict, limit: int, offset: int) -> Tuple[List[Dict[str, Any]], int]:
    query_config = {
        "tabela": TABLE_DAILY_OCCUPANCY,
        "colunas_desejadas": "resort, empresa, data, hosptotal, lazer, eventos, mes, ano, dia",
        "filtros_flexiveis": {
            "resort": "resort",
            "hotel": "resort",
            "empresa": "empresa"
        },
        "filtros_exatos": {
            "mes": "mes::integer",
            "ano": "ano::integer",
            "dia": "dia::integer"
        },
        "ordenacao_padrao": "data DESC" 
    }
    return _execute_standard_query(query_config, filtros, limit, offset)



def summarize_guests_by_month(filtros: dict, limit: int, offset: int) -> Tuple[List[Dict[str, Any]], int, str | None]:
    resort_input = _g(filtros, "resort", "hotel")
    month_input = _g(filtros, "mes", "periodo")
    year = _g(filtros, "ano")

    resort = _normalize_resort_code(resort_input) if resort_input else None
    month = _translate_period_to_number(month_input) if month_input else None

    if not year:
        raise ValueError("Filtro 'ano' é obrigatório.")

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        if resort and month:
            query = f"""
                SELECT 
                    resort,
                    mes::integer as mes,
                    SUM(eventos) as total_eventos,
                    SUM(lazer) as total_lazer,
                    SUM(hosptotal) as total_hospedes,
                    COUNT(DISTINCT dia) as dias_apurados
                FROM "{TABLE_DAILY_OCCUPANCY}"
                WHERE unaccent(lower(resort)) = unaccent(lower(%s))
                  AND mes::integer = %s
                  AND ano::integer = %s
                GROUP BY resort, mes
                ORDER BY mes;
            """
            params = [resort, int(month), int(year)]
            where_sql = 'WHERE unaccent(lower(resort)) = unaccent(lower(%s)) AND mes::integer = %s AND ano::integer = %s'
        elif resort and not month:
            query = f"""
                SELECT 
                    resort,
                    mes::integer as mes,
                    SUM(eventos) as total_eventos,
                    SUM(lazer) as total_lazer,
                    SUM(hosptotal) as total_hospedes,
                    COUNT(DISTINCT dia) as dias_apurados
                FROM "{TABLE_DAILY_OCCUPANCY}"
                WHERE unaccent(lower(resort)) = unaccent(lower(%s))
                  AND ano::integer = %s
                GROUP BY resort, mes
                ORDER BY mes;
            """
            params = [resort, int(year)]
            where_sql = 'WHERE unaccent(lower(resort)) = unaccent(lower(%s)) AND ano::integer = %s'
        elif month and not resort:
            query = f"""
                SELECT 
                    resort,
                    mes::integer as mes,
                    SUM(eventos) as total_eventos,
                    SUM(lazer) as total_lazer,
                    SUM(hosptotal) as total_hospedes,
                    COUNT(DISTINCT dia) as dias_apurados
                FROM "{TABLE_DAILY_OCCUPANCY}"
                WHERE mes::integer = %s
                  AND ano::integer = %s
                GROUP BY resort, mes
                ORDER BY resort;
            """
            params = [int(month), int(year)]
            where_sql = 'WHERE mes::integer = %s AND ano::integer = %s'
        else:
            query = f"""
                SELECT 
                    resort,
                    mes::integer as mes,
                    SUM(eventos) as total_eventos,
                    SUM(lazer) as total_lazer,
                    SUM(hosptotal) as total_hospedes,
                    COUNT(DISTINCT dia) as dias_apurados
                FROM "{TABLE_DAILY_OCCUPANCY}"
                WHERE ano::integer = %s
                GROUP BY resort, mes
                ORDER BY resort, mes;
            """
            params = [int(year)]
            where_sql = 'WHERE ano::integer = %s'

        cur.execute(query, tuple(params))
        columns = [_format_column_name(desc[0], {}) for desc in cur.description]
        data = [dict(zip(columns, row)) for row in cur.fetchall()]

        if data:
            is_specific_resort_month = bool(resort and month and year)
            if not is_specific_resort_month:
                total_events = sum(d["total_eventos"] or 0 for d in data)
                total_leisure = sum(d["total_lazer"] or 0 for d in data)
                total_guests = sum(d["total_hospedes"] or 0 for d in data)
                summary = {
                    "resort": "OVERALL TOTAL",
                    "mes": month if month else ("TOTAL" if not resort else None),
                    "total_eventos": total_events,
                    "total_lazer": total_leisure,
                    "total_hospedes": total_guests,
                    "dias_apurados": None
                }
                data.append(summary)

        data_until = _get_latest_date(conn, TABLE_DAILY_OCCUPANCY, where_sql, params, "data")

        return data, len(data), data_until
    finally:
        if conn: conn.close()



def calculate_complaint_per_guest_index(filtros: dict, limit: int, offset: int) -> Tuple[List[Dict[str, Any]], int, str | None]:
    resort_input = _g(filtros, "hotel", "resort")
    month_input = _g(filtros, "mes", "periodo")
    year = _g(filtros, "ano")
    department_input = _g(filtros, "cr", "setor")

    resort_code = _normalize_resort_code(resort_input)
    month = _translate_period_to_number(month_input)

    if not all([resort_code, month, year]):
        raise ValueError("Filtros 'hotel'/'resort', 'mes'/'periodo' e 'ano' são obrigatórios.")

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        is_group_query = resort_code == 'all_resorts'

        # 1. BUSCAR TOTAL DE RECLAMAÇÕES
        where_complaints_parts = ["mes = %s", "ano = %s", "tipocomentario = 'Reclamação'"]
        params_complaints = [int(month), int(year)]

        if not is_group_query:
            where_complaints_parts.insert(0, "unaccent(lower(hotel)) = unaccent(lower(%s))")
            params_complaints.insert(0, resort_code)

        if department_input and department_input.strip():
            where_complaints_parts.append("unaccent(lower(cr)) = unaccent(lower(%s))")
            params_complaints.append(department_input.strip())
            
        where_complaints = "WHERE " + " AND ".join(where_complaints_parts)
        cur.execute(f'SELECT COUNT(*) FROM "{TABLE_GUEST_FEEDBACK}" {where_complaints};', tuple(params_complaints))
        total_complaints = cur.fetchone()[0] or 0

        # 2. BUSCAR TOTAL DE HÓSPEDES
        where_occupancy_parts = ["mes::integer = %s", "ano::integer = %s"]
        params_occupancy = [int(month), int(year)]

        if not is_group_query:
            where_occupancy_parts.insert(0, "unaccent(lower(resort)) = unaccent(lower(%s))")
            params_occupancy.insert(0, resort_code)

        where_occupancy = "WHERE " + " AND ".join(where_occupancy_parts)
        cur.execute(f'SELECT SUM(hosptotal) FROM "{TABLE_DAILY_OCCUPANCY}" {where_occupancy};', tuple(params_occupancy))
        total_guests = (cur.fetchone() or [0])[0] or 0
        
        # 3. BUSCAR META DO PERÍODO
        period_target = 0.0
        where_target_parts = [
            "unaccent(lower(hotel)) = unaccent(lower(%s))",
            "mes = %s",
            "ano = %s"
        ]
        params_target = [resort_code, int(month), int(year)]

        if department_input and department_input.strip():
            where_target_parts.append("unaccent(lower(cr)) = unaccent(lower(%s))")
            params_target.append(department_input.strip())
            query_target = f'SELECT meta FROM "{TABLE_DEPARTMENT_COMPLAINT_TARGETS}" WHERE {" AND ".join(where_target_parts)}'
        else:
            query_target = f'SELECT SUM(meta) FROM "{TABLE_DEPARTMENT_COMPLAINT_TARGETS}" WHERE {" AND ".join(where_target_parts)}'
        
        cur.execute(query_target, tuple(params_target))
        target_result = cur.fetchone()
        if target_result and target_result[0] is not None:
            period_target = target_result[0]

        # 4. CALCULAR ÍNDICE E MONTAR RESULTADO
        percentage_index = round((total_complaints / float(total_guests)) * 100, 2) if total_guests > 0 else 0.0

        data_until_complaints = _get_latest_date(conn, TABLE_GUEST_FEEDBACK, where_complaints, params_complaints, "datapreenchimento")
        data_until_occupancy    = _get_latest_date(conn, TABLE_DAILY_OCCUPANCY,    where_occupancy,    params_occupancy,    "data")

        candidates = [d for d in [data_until_complaints, data_until_occupancy] if d]
        data_until = min(candidates) if len(candidates) == 2 else (candidates[0] if len(candidates) == 1 else None)

        result = {
            "resort_code": "All Resorts" if is_group_query else resort_code,
            "year": int(year),
            "month": int(month),
            "department": (department_input.strip() if department_input else "All"),
            "total_complaints_in_period": int(total_complaints),
            "total_guests_in_period": float(total_guests),
            "complaint_per_guest_index": float(percentage_index),
            "complaint_per_guest_index_target": round(float(period_target), 2)
        }
        return [result], 1, data_until

    except Exception as e:
        print(f"ERRO em calculate_complaint_per_guest_index: {traceback.format_exc()}")
        return [{"erro": f"Falha ao processar o cálculo: {e}"}], 1, None
    finally:
        if conn: conn.close()
