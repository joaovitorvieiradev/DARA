import traceback
from typing import List, Dict, Any, Tuple
from tcf.db_reader import get_db_connection

# =========================================================
# 1. FUNÇÕES AUXILIARES E UTILITÁRIOS (TCF)
# =========================================================

MONTH_NAME_TO_NUMBER_MAP = {
    "janeiro": "1", "jan": "1",
    "fevereiro": "2", "fev": "2",
    "marco": "3", "março": "3", "mar": "3",
    "abril": "4", "abr": "4",
    "maio": "5", "mai": "5",
    "junho": "6", "jun": "6",
    "julho": "7", "jul": "7",
    "agosto": "8", "ago": "8",
    "setembro": "9", "set": "9",
    "outubro": "10", "out": "10",
    "novembro": "11", "nov": "11",
    "dezembro": "12", "dez": "12",
}

RESORT_CODES = ['resort_alpha', 'resort_beta', 'resort_gamma', 'resort_delta', "resort_epsilon", "all_resorts", "corp_hq", "partner_brand"]

COLUMN_NAME_MAP_HR = {
    "hotel": "resort_code",
    "ano": "year",
    "mes": "month",
    "setor": "department",
    "cr": "department",
    "horasnegativas": "negative_hours",
    "horaspositivas": "positive_hours",
    "nome": "employee_name",
    "emocionador": "employee_name",
    "horas": "balance_hours",
    "data": "date"
}

def _format_hr_column_name(column_name: str) -> str:
    """Usa o mapa de RH para traduzir os nomes das colunas do banco."""
    column_key = column_name.lower().replace(" ", "")
    return COLUMN_NAME_MAP_HR.get(column_key, column_name.lower())

def _g(filtros: dict, *keys: str):
    """Retorna o primeiro valor presente nas chaves informadas (case-insensitive)."""
    for k in keys:
        if k in filtros: return filtros.get(k)
        lk = k.lower()
        if lk in filtros: return filtros.get(lk)
    return None

def _normalize_resort_code(resort_value: Any) -> Any:
    """Verifica se um nome canônico de hotel está dentro da string de input e retorna o nome canônico."""
    if not isinstance(resort_value, str):
        return resort_value
    norm_valor = resort_value.lower().replace('á', 'a').replace('â', 'a').replace('ã', 'a').replace('ç', 'c')
    for canonical in RESORT_CODES:
        if canonical in norm_valor:
            return canonical
    return resort_value

def _build_flexible_where_clause(
    where_clauses: list, params: list, filtros: dict, filter_key: str, db_column_name: str
):
    """Adiciona uma cláusula WHERE flexível, normalizando nomes de hotel se necessário."""
    value = _g(filtros, filter_key)
    if db_column_name.lower() in ('hotel', 'resort'):
        value = _normalize_resort_code(value)
    if value and value != 'all_resorts':
        where_clauses.append(f'TRIM(unaccent(lower({db_column_name}))) ILIKE unaccent(lower(%s))')
        params.append(f'%{value}%')

def _normalize_month_value(month_value: Any) -> Any:
    """Normaliza o input de mês (nome ou número) para o valor numérico em string."""
    if isinstance(month_value, int):
        return str(month_value)
    if not isinstance(month_value, str):
        return month_value
    
    normalized_key = month_value.lower().strip()
    return MONTH_NAME_TO_NUMBER_MAP.get(normalized_key, month_value)


def _execute_standard_query(config: dict, filtros: dict, limit: int, offset: int) -> Tuple[List[Dict[str, Any]], int]:
    """Motor genérico que executa consultas de listagem para o domínio de RH."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        table = config["tabela"]
        flexible_filters = config.get("filtros_flexiveis", {})
        exact_filters = config.get("filtros_exatos", {})
        gte_filters = config.get("filtros_gte", {})
        lte_filters = config.get("filtros_lte", {})
        
        where_clauses, params = [], []
        
        for api_key, col_name in flexible_filters.items():
            if _g(filtros, api_key):
                _build_flexible_where_clause(where_clauses, params, filtros, api_key, col_name)
        
        for api_key, col_name in exact_filters.items():
            value = _g(filtros, api_key)
            if api_key.lower() == 'mes': value = _normalize_month_value(value)
            if value is not None:
                where_clauses.append(f'{col_name} = %s')
                params.append(value)
        
        for api_key, col_name in gte_filters.items():
            value = _g(filtros, api_key)
            if value is not None:
                try:
                    float(value)
                    where_clauses.append(f'{col_name} >= %s')
                    params.append(value)
                except (ValueError, TypeError): pass

        for api_key, col_name in lte_filters.items():
            value = _g(filtros, api_key)
            if value is not None:
                try:
                    float(value)
                    where_clauses.append(f'{col_name} <= %s')
                    params.append(value)
                except (ValueError, TypeError): pass

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        
        count_query = f'SELECT COUNT(*) FROM "{table}" {where_sql}'
        cur.execute(count_query, tuple(params))
        total_records = cur.fetchone()[0]

        query = f'SELECT {config.get("colunas_desejadas", "*")} FROM "{table}" {where_sql} ORDER BY {config.get("ordenacao_padrao", "1")} LIMIT %s OFFSET %s'
        cur.execute(query, tuple(params + [limit, offset]))
        
        columns = [_format_hr_column_name(desc[0]) for desc in cur.description]
        data = [dict(zip(columns, row)) for row in cur.fetchall()]
        
        return data, total_records
    finally:
        if conn: conn.close()

# =========================================================
# 3. CONSTANTES DO MÓDULO (TCF)
# =========================================================

TABLE_POSITIVE_OVERTIME = "overtime_positive"
TABLE_NEGATIVE_OVERTIME = "overtime_negative"
TABLE_EMPLOYEE_OVERTIME_BALANCE = "employee_overtime_balance"

# =========================================================
# 4. AS FERRAMENTAS FINAIS (TCF)
# =========================================================

def get_employee_overtime_balance(filtros: dict, limit: int = 50, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    """
    Consulta o saldo de banco de horas de funcionários. Se o filtro 'horas' for usado,
    a busca e o ranking se adaptam: para horas positivas, busca >= e ordena do maior saldo para o menor.
    Para horas negativas, busca <= e ordena do maior débito para o menor.
    """
    hotel = _g(filtros, 'hotel')
    year = _g(filtros, 'ano')
    month = _g(filtros, 'mes')
    name = _g(filtros, 'nome', 'emocionador', 'employee')
    hours_filter = _g(filtros, 'horas')

    if not hotel or not year:
        return ([{"erro": "Para esta consulta, 'hotel' e 'ano' são filtros obrigatórios."}], 0)
    if not name and not month:
        return ([{"erro": "É necessário fornecer um 'mes' ou um 'nome' de funcionário para a consulta."}], 0)

    order_by = "nome ASC, ano ASC, mes ASC" 
    gte_filters = {}
    lte_filters = {}

    if hours_filter is not None:
        try:
            hours_value = int(hours_filter)
            if hours_value < 0:
                order_by = "horas ASC, nome ASC"
                lte_filters = {"horas": "horas::integer"}
            else:
                order_by = "horas DESC, nome ASC"
                gte_filters = {"horas": "horas::integer"}
        except (ValueError, TypeError):
            pass

    config = {
        "tabela": TABLE_EMPLOYEE_OVERTIME_BALANCE,
        "colunas_desejadas": "hotel, ano, mes, cr, nome, horas",
        "filtros_flexiveis": {"hotel": "hotel", "setor": "cr", "cr": "cr", "nome": "nome"},
        "filtros_exatos": {"ano": "ano::integer", "mes": "mes::integer"},
        "filtros_gte": gte_filters,
        "filtros_lte": lte_filters,
        "ordenacao_padrao": order_by
    }
    
    return _execute_standard_query(config, filtros, limit, offset)

def get_department_overtime_balance(filtros: dict, limit: int, offset: int) -> Tuple[List[Dict[str, Any]], int, Dict[str, Any]]:
    """
    Função com dupla finalidade para analisar o banco de horas.
    - Se um 'hotel' é fornecido, consolida as horas por DEPARTAMENTO dentro daquele hotel.
    - Se 'hotel' é omitido, cria um RANKING consolidado por HOTEL para toda a rede.
    'ano' é sempre obrigatório.
    """
    hotel = _g(filtros, 'hotel', 'resort')
    year = _g(filtros, 'ano')

    if not year:
        raise ValueError("O filtro 'ano' é obrigatório para esta análise.")

    if hotel:
        # ===== COMPORTAMENTO 1: ANÁLISE POR DEPARTAMENTO (DENTRO DE UM HOTEL) =====
        month = _g(filtros, 'mes')
        hours_filter = _g(filtros, 'horas')
        if not month and not hours_filter:
            raise ValueError("Para análise por departamento, é necessário fornecer um 'mes' ou um filtro de 'horas'.")
        
        return _query_by_department(filtros)
    else:
        # ===== COMPORTAMENTO 2: ANÁLISE POR HOTEL (RANKING DA REDE) =====
        data, total = _rank_by_resort(filtros)
        return data, total, {} # Retorna um resumo vazio, pois o próprio dado já é o resumo

def _query_by_department(filtros: dict) -> Tuple[List[Dict[str, Any]], int, Dict[str, Any]]:
    """Função interna que executa a consulta consolidada por departamento."""
    hotel = _g(filtros, 'hotel', 'resort')
    year = _g(filtros, 'ano')
    month = _g(filtros, 'mes')
    department_filter = _g(filtros, 'setor', 'cr')
    hours_filter = _g(filtros, 'horas')
    
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        base_where_clauses = ["TRIM(unaccent(lower(hotel))) ILIKE TRIM(unaccent(lower(%s)))", "ano = %s"]
        base_params = [hotel, year]

        dynamic_where_clauses = []
        dynamic_params = []
        
        if month:
            dynamic_where_clauses.append("mes = %s")
            dynamic_params.append(month)
        
        if department_filter:
            dynamic_where_clauses.append("TRIM(unaccent(lower(cr))) = TRIM(unaccent(lower(%s)))")
            dynamic_params.append(department_filter)

        full_where_clause = "WHERE " + " AND ".join(base_where_clauses + dynamic_where_clauses)
        
        subquery_params = base_params + dynamic_params
        full_params = tuple(subquery_params + subquery_params)

        query = f"""
            SELECT 
                COALESCE(p.cr_original, n.cr_original) AS cr, 
                COALESCE(p.total_positivas, 0) AS horas_positivas, 
                COALESCE(n.total_negativas, 0) AS horas_negativas
            FROM 
                (SELECT 
                    TRIM(unaccent(lower(cr))) as cr_normalizado,
                    MIN(cr) as cr_original,
                    SUM(horaspositiva) AS total_positivas 
                FROM {TABLE_POSITIVE_OVERTIME} 
                {full_where_clause} 
                GROUP BY TRIM(unaccent(lower(cr)))) AS p
            FULL OUTER JOIN 
                (SELECT 
                    TRIM(unaccent(lower(cr))) as cr_normalizado,
                    MIN(cr) as cr_original,
                    SUM(horasnegativas) AS total_negativas 
                FROM {TABLE_NEGATIVE_OVERTIME} 
                {full_where_clause} 
                GROUP BY TRIM(unaccent(lower(cr)))) AS n 
            ON p.cr_normalizado = n.cr_normalizado
            ORDER BY cr;
        """

        cur.execute(query, full_params)
        columns = [_format_hr_column_name(desc[0]) for desc in cur.description]
        data_by_dept = [dict(zip(columns, row)) for row in cur.fetchall()]

        if hours_filter is not None:
            try:
                hours_str = str(hours_filter)
                if hours_str.startswith('-'):
                    abs_value = int(hours_str[1:])
                    filtered_data = [d for d in data_by_dept if d['negative_hours'] >= abs_value]
                    data_by_dept = sorted(filtered_data, key=lambda x: x['negative_hours'], reverse=True)
                else:
                    abs_value = int(hours_str)
                    filtered_data = [d for d in data_by_dept if d['positive_hours'] >= abs_value]
                    data_by_dept = sorted(filtered_data, key=lambda x: x['positive_hours'], reverse=True)
            except (ValueError, TypeError): pass

        total_summary = {}
        if not department_filter:
            total_positives = sum(item['positive_hours'] for item in data_by_dept)
            total_negatives = sum(item['negative_hours'] for item in data_by_dept)
            overall_balance = total_positives - total_negatives
            total_summary = {"total_positive_hours": total_positives, "total_negative_hours": total_negatives, "resort_overall_balance": overall_balance}
        
        return data_by_dept, len(data_by_dept), total_summary
    finally:
        if conn: conn.close()

def _rank_by_resort(filtros: dict) -> Tuple[List[Dict[str, Any]], int]:
    """Função interna que executa o ranking de hotéis e adiciona o total do Grupo."""
    year = _g(filtros, 'ano')
    month = _g(filtros, 'mes')
    
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        params = [year]
        where_clause = "WHERE ano = %s"
        if month:
            where_clause += " AND mes = %s"
            params.append(month)
        full_params = tuple(params * 2)
        query = f"""
            SELECT COALESCE(p.hotel, n.hotel) AS hotel, COALESCE(p.total_positivas, 0) AS horas_positivas, COALESCE(n.total_negativas, 0) AS horas_negativas
            FROM (SELECT hotel, SUM(horaspositiva) AS total_positivas FROM {TABLE_POSITIVE_OVERTIME} {where_clause} GROUP BY hotel) AS p
            FULL OUTER JOIN (SELECT hotel, SUM(horasnegativas) AS total_negativas FROM {TABLE_NEGATIVE_OVERTIME} {where_clause} GROUP BY hotel) AS n ON p.hotel = n.hotel
            ORDER BY horas_positivas DESC;
        """
        cur.execute(query, full_params)
        columns = [_format_hr_column_name(desc[0]) for desc in cur.description]
        ranking_data = [dict(zip(columns, row)) for row in cur.fetchall()]
        
        if ranking_data and len(ranking_data) > 1:
            group_total_positives = sum(item.get('positive_hours', 0) for item in ranking_data)
            group_total_negatives = sum(item.get('negative_hours', 0) for item in ranking_data)

            group_summary = {
                "resort_code": "Group",
                "positive_hours": group_total_positives,
                "negative_hours": group_total_negatives
            }
            ranking_data.append(group_summary)

        return ranking_data, len(ranking_data)
    finally:
        if conn: conn.close()
