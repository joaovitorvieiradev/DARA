import traceback
from typing import List, Dict, Any, Tuple
from operacoes.db_reader import get_db_connection

# =========================================================
# 1. CONSTANTES E MAPAS DE NORMALIZAÇÃO
# =========================================================

AGGREGATED_PERIOD_MAP = {
    "1st semester": "H1", "first semester": "H1",
    "2nd semester": "H2", "second semester": "H2",
    "year to date": "YTD", "ytd": "YTD", "total year": "YTD",
    "annual": "Annual", "full year": "YTD"
}

RESORT_CODES = ['resort_alpha', 'resort_beta', 'resort_gamma', 'resort_delta', 'resort_epsilon', 'all_resorts']

COLUMN_NAME_MAP_INDICATORS = {
    "hotel": "resort_code", "ano": "year", "periodo": "period", "reclamacaometa": "complaint_target",
    "reclamacaoreal": "complaint_actual", "npsmeta": "nps_target", "npsreal": "nps_actual",
    "grimeta": "gri_target", "grireal": "gri_actual", "receitaextrameta": "extra_revenue_target",
    "receitaextrareal": "extra_revenue_actual", "custodealimentosmeta": "food_cost_target",
    "custodealimentosreal": "food_cost_actual", "cmvdealimentosmeta": "food_cogs_target",
    "cmvdealimentosreal": "food_cogs_actual", "custodebebidasmeta": "beverage_cost_target",
    "custodebebidasreal": "beverage_cost_actual", "cmvdebebidasmeta": "beverage_cogs_target",
    "cmvdebebidasreal": "beverage_cogs_actual", "custodeaebmeta": "fb_cost_target",
    "custodeaebreal": "fb_cost_actual", "cmvaebmeta": "fb_cogs_target",
    "cmvaebreal": "fb_cogs_actual", "id": "id"
}

TABLE_BUSINESS_INDICATORS = "business_indicators"

# =========================================================
# 2. FUNÇÕES AUXILIARES INTERNAS
# =========================================================

def _g(filtros: dict, *keys: str) -> Any:
    """Retorna o primeiro valor presente nas chaves informadas (case-insensitive)."""
    for k in keys:
        for var in (k, k.lower(), k.upper(), k.capitalize()):
            if var in filtros:
                return filtros[var]
    return None

def _format_column_name(column_name: str) -> str:
    """Usa o mapa para traduzir os nomes de colunas do banco para o padrão snake_case."""
    column_name_lower = column_name.lower()
    return COLUMN_NAME_MAP_INDICATORS.get(column_name_lower, column_name_lower)

def _normalize_aggregated_period(period_value: Any) -> Any:
    """Normaliza o input de período AGREGADO para o valor canônico esperado pelo banco."""
    if not isinstance(period_value, str):
        return period_value
    try:
        normalized_key = period_value.lower().strip().replace('º', 'o').replace('ª', 'a')
        return AGGREGATED_PERIOD_MAP.get(normalized_key, period_value)
    except Exception:
        return period_value

def _transform_to_nested_json(db_row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transforma uma linha de resultado do banco (flat) em uma estrutura JSON
    aninhada e mais intuitiva.
    """
    result = {
        "year": db_row.get("year"),
        "resort_code": db_row.get("resort_code"),
        "period": db_row.get("period"),
        "status": "closed",
        "indicators": {}
    }

    # Agrupa os indicadores (actual e target)
    for key, value in db_row.items():
        if key.endswith("_actual") or key.endswith("_target"):
            parts = key.split('_')
            indicator_name = "_".join(parts[:-1])
            value_type = parts[-1]

            if indicator_name not in result["indicators"]:
                result["indicators"][indicator_name] = {}

            # Atribui o valor diretamente do banco, sem conversões
            result["indicators"][indicator_name][value_type] = value

    return result

# =========================================================
# 3. EXECUTOR DE CONSULTA GENÉRICO
# =========================================================

def _execute_indicators_query(filtros: dict, limit: int, offset: int) -> Tuple[List[Dict[str, Any]], int]:
    """
    Motor genérico que executa consultas na tabela de indicadores.
    """
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        config = {
            "tabela": TABLE_BUSINESS_INDICATORS,
            "filtros_exatos": {"year": "ano::integer", "query_period": "periodo"},
            "filtros_flexiveis": {"resort_code": "hotel"},
            "ordenacao_padrao": "ano, periodo"
        }

        where_clauses, params = [], []
        
        for api_key, col_name in config["filtros_flexiveis"].items():
            valor = _g(filtros, api_key, "hotel") # Aceita 'hotel' como alias para 'resort_code'
            if valor:
                where_clauses.append(f'unaccent(lower({col_name})) = unaccent(lower(%s))')
                params.append(valor)

        for api_key, col_name in config["filtros_exatos"].items():
            valor = _g(filtros, api_key)
            if valor is not None:
                where_clauses.append(f'{col_name} = %s')
                params.append(valor)
        
        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        
        count_query = f'SELECT COUNT(*) FROM "{config["tabela"]}" {where_sql}'
        cur.execute(count_query, tuple(params))
        total_registros = cur.fetchone()[0]

        query = f'SELECT * FROM "{config["tabela"]}" {where_sql} ORDER BY {config["ordenacao_padrao"]} LIMIT %s OFFSET %s'
        cur.execute(query, tuple(params + [limit, offset]))
        
        colunas = [_format_column_name(desc[0]) for desc in cur.description]
        dados = [dict(zip(colunas, row)) for row in cur.fetchall()]
        
        return dados, total_registros
    finally:
        if conn:
            conn.close()

# =========================================================
# 4. FUNÇÃO PRINCIPAL (FERRAMENTA DA API)
# =========================================================

def get_closed_period_indicators(filtros: dict, limit: int, offset: int) -> Tuple[List[Dict[str, Any]], int]:
    """
    Consulta indicadores de períodos já fechados (mês, semestre ou ano),
    retornando os dados em uma estrutura JSON aninhada.
    Não deve ser utilizado para consultar dados do mês atual.
    """
    processed_filters = filtros.copy()
    month = _g(processed_filters, 'month', 'mes')
    aggregated_period = _g(processed_filters, 'period')
    final_db_value = None

    if aggregated_period:
        final_db_value = _normalize_aggregated_period(str(aggregated_period))
    elif month:
        final_db_value = str(month)
    
    if final_db_value:
        processed_filters['query_period'] = final_db_value

    db_data, total_records = _execute_indicators_query(processed_filters, limit, offset)

    formatted_data = [_transform_to_nested_json(row) for row in db_data]
    
    return formatted_data, total_records
