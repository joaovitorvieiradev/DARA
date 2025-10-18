import traceback
from typing import List, Dict, Any, Tuple
from tcf.db_reader import get_db_connection

# =========================================================
# 1. CONSTANTES E MAPAS GLOBAIS
# =========================================================

MONTH_NAME_TO_NUMBER_MAP = {
    "janeiro": "1", "jan": "1", "fevereiro": "2", "fev": "2", "marco": "3", "março": "3", "mar": "3",
    "abril": "4", "abr": "4", "maio": "5", "mai": "5", "junho": "6", "jun": "6", "julho": "7", "jul": "7",
    "agosto": "8", "ago": "8", "setembro": "9", "set": "9", "outubro": "10", "out": "10",
    "novembro": "11", "nov": "11", "dezembro": "12", "dez": "12",
}

RESORT_CODES = ['resort_alpha', 'resort_beta', 'resort_gamma', 'resort_delta', "resort_epsilon", "all_resorts", "corp_hq", "partner_brand"]

# Nomes das tabelas no banco de dados
TABLE_SENTIMENT_BY_RESORT = "employee_sentiment_by_resort"
TABLE_SENTIMENT_BY_DEPARTMENT = "employee_sentiment_by_department"
TABLE_SENTIMENT_SURVEYS = "employee_sentiment_surveys"

# Mapeamento dos nomes de colunas do banco para nomes amigáveis no JSON de resposta
COLUMN_NAME_MAP_SENTIMENT = {
    # Tabelas Hotel e Setores
    "dimensaonova": "dimension",
    "taxageraldeadesao": "overall_adherence_rate",
    "score": "score",
    "hotel": "resort_code",
    "mes": "month",
    "ano": "year",
    "scorehotelsituacao": "score_status",
    "notas": "scores",
    # Tabela Setores
    "lideresdiretos": "direct_leader",
    "cr": "department",
    "nivel": "level",
    "lideranca": "leadership",
    # Tabela Enviados
    "destinatario": "employee_name",
    "cargo": "position",
    "grupos": "groups",
    "lideres": "leader",
    "status": "status",
    "dataehora": "timestamp",
    "egerente": "is_manager",
    "meses_ocorrencias": "months_of_occurrence",
}

# =========================================================
# 2. FUNÇÕES AUXILIARES E UTILITÁRIOS
# =========================================================

def _g(filtros: dict, *keys: str):
    """Retorna o primeiro valor presente nas chaves informadas (case-insensitive)."""
    filtros_lower = {k.lower(): v for k, v in filtros.items()}
    for k in keys:
        if k.lower() in filtros_lower:
            return filtros_lower[k.lower()]
    return None


def _normalize_multiple_months(months_value: Any) -> Tuple[str, ...]:
    """Converte uma string de meses separados por vírgula em uma tupla de números."""
    if not isinstance(months_value, str):
        return tuple()
    
    months_list = [m.strip() for m in months_value.split(',')]
    normalized_months = [_normalize_month_value(m) for m in months_list]
    
    return tuple(m for m in normalized_months if m)


def _normalize_resort_code(resort_value: Any) -> Any:
    """Retorna o nome canônico do hotel a partir de uma string."""
    if not isinstance(resort_value, str): return resort_value
    norm_valor = resort_value.lower().replace('á', 'a').replace('â', 'a').replace('ã', 'a').replace('ç', 'c')
    for canonical in RESORT_CODES:
        if canonical in norm_valor:
            return canonical
    return resort_value

def _normalize_month_value(month_value: Any) -> Any:
    """Normaliza o input de mês (nome ou número) para o valor numérico em string."""
    if isinstance(month_value, int): return str(month_value)
    if not isinstance(month_value, str): return month_value
    normalized_key = month_value.lower().strip().replace('ç', 'c')
    return MONTH_NAME_TO_NUMBER_MAP.get(normalized_key, month_value)

def _execute_sentiment_query(config: dict, filtros: dict, limit: int, offset: int) -> Tuple[List[Dict[str, Any]], int]:
    """Motor genérico para executar consultas nas tabelas do Felicitômetro."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        table = config["tabela"]
        flexible_filters = config.get("filtros_flexiveis", {})
        exact_filters = config.get("filtros_exatos", {})
        
        where_clauses, params = [], []
        
        # Filtros com LIKE (parciais, case-insensitive)
        for api_key, col_name in flexible_filters.items():
            value = _g(filtros, api_key)
            if value:
                if col_name.lower() in ('hotel', 'resort'): value = _normalize_resort_code(value)
                if value != 'all_resorts':
                    where_clauses.append(f'unaccent(lower({col_name})) LIKE unaccent(lower(%s))')
                    params.append(f'%{value}%')
        
        # Filtros com = (exatos)
        for api_key, col_name in exact_filters.items():
            value = _g(filtros, api_key)
            if api_key.lower() == 'mes': value = _normalize_month_value(value)
            if value is not None:
                where_clauses.append(f'{col_name} = %s')
                params.append(value)

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        
        count_query = f'SELECT COUNT(*) FROM "{table}" {where_sql}'
        cur.execute(count_query, tuple(params))
        total_records = cur.fetchone()[0]

        query = f'SELECT * FROM "{table}" {where_sql} ORDER BY {config.get("ordenacao_padrao", "1")} LIMIT %s OFFSET %s'
        cur.execute(query, tuple(params + [limit, offset]))
        
        db_columns = [desc[0] for desc in cur.description]
        formatted_columns = [COLUMN_NAME_MAP_SENTIMENT.get(c, c) for c in db_columns]
        data = [dict(zip(formatted_columns, row)) for row in cur.fetchall()]
        
        return data, total_records
    finally:
        if conn: conn.close()

# =========================================================
# 3. FUNÇÕES PÚBLICAS DE ANÁLISE (FERRAMENTAS)
# =========================================================

def get_resort_adherence(filtros: dict, limit: int = 20, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    """
    Consulta a taxa de adesão e o score geral do Felicitômetro por hotel ou para o grupo.
    Ideal para perguntas sobre a nota geral de um hotel específico ou da rede.
    Filtros possíveis: hotel, ano, mes.
    """
    config = {
        "tabela": TABLE_SENTIMENT_BY_RESORT,
        "filtros_flexiveis": {"hotel": "hotel"},
        "filtros_exatos": {"ano": "ano", "mes": "mes"},
        "ordenacao_padrao": "ano DESC, mes DESC, taxageraldeadesao DESC"
    }

    data, total_records = _execute_sentiment_query(config, filtros, limit, offset)

    for item in data:
        adherence_key = 'overall_adherence_rate'
        if adherence_key in item and isinstance(item.get(adherence_key), (int, float)):
            item[adherence_key] = round(item[adherence_key] * 100, 2)

    return data, total_records

def get_department_adherence(filtros: dict, limit: int = 50, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    """
    Consulta a taxa de adesão e o score do Felicitômetro por setor (CR) e líder.
    Ideal para perguntas sobre o desempenho de setores ou líderes específicos.
    Filtros possíveis: hotel, ano, mes, cr, setor, lider.
    """
    query_filters = filtros.copy()

    department_value = _g(filtros, 'cr', 'setor', 'department')
    
    if department_value:
        query_filters['cr'] = department_value

    config = {
        "tabela": TABLE_SENTIMENT_BY_DEPARTMENT,
        "filtros_flexiveis": {
            "hotel": "hotel",
            "cr": "cr",
            "lider": "lideresdiretos"
        },
        "filtros_exatos": {"ano": "ano", "mes": "mes"},
        "ordenacao_padrao": "ano DESC, mes DESC, taxageraldeadesao DESC, cr ASC"
    }
    
    data, total_records = _execute_sentiment_query(config, query_filters, limit, offset)

    for item in data:
        adherence_key = 'overall_adherence_rate'
        if adherence_key in item and isinstance(item.get(adherence_key), (int, float)):
            item[adherence_key] = round(item[adherence_key] * 100, 2)
            
    return data, total_records

def get_survey_status(filtros: dict, limit: int = 100, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    """
    Lista os funcionários e o status de resposta do Felicitômetro (Respondido, Em Aberto, etc.).
    Ideal para identificar quem respondeu ou não a pesquisa em um determinado período.
    Filtros possíveis: hotel, ano, mes, cr, setor, destinatario, nome, lider, status, cargo.
    """
    query_filters = filtros.copy()

    department_value = _g(filtros, 'cr', 'setor', 'department')
    if department_value:
        query_filters['cr'] = department_value

    recipient_value = _g(filtros, 'destinatario', 'nome', 'employee')
    if recipient_value:
        query_filters['destinatario'] = recipient_value

    config = {
        "tabela": TABLE_SENTIMENT_SURVEYS,
        "filtros_flexiveis": {
            "hotel": "hotel",
            "cr": "cr",
            "destinatario": "destinatario",
            "lider": "lideres",
            "status": "status",
            "cargo": "cargo"
        },
        "filtros_exatos": {"ano": "ano", "mes": "mes"},
        "ordenacao_padrao": "dataehora DESC"
    }
    
    return _execute_sentiment_query(config, query_filters, limit, offset)

def rank_by_survey_status(filtros: dict, limit: int = 5, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    """
    Cria um ranking (Top 5) de funcionários ou consulta o status de um funcionário específico.
    Mostra o total de ocorrências, os meses e o hotel.
    Filtros obrigatórios: ano, status.
    Filtros possíveis: hotel, mes (múltiplos com vírgula), destinatario (ou nome).
    """
    year = _g(filtros, 'ano')
    status_filter = _g(filtros, 'status')
    if not year or not status_filter:
        raise ValueError("Os filtros 'ano' e 'status' são obrigatórios para esta análise.")

    status_map = {
        "respondido": ('Respondido',), "em aberto": ('Em Aberto',), "enviado": ('Enviado',),
        "nao respondido": ('Enviado', 'Em Aberto'), "não respondido": ('Enviado', 'Em Aberto')
    }
    status_values = status_map.get(status_filter.lower(), (status_filter,))

    where_clauses, params = ["ano = %s"], [year]
    
    status_placeholder = ", ".join(["%s"] * len(status_values))
    where_clauses.append(f"status IN ({status_placeholder})")
    params.extend(status_values)
    
    if _g(filtros, 'hotel', 'resort'):
        hotel = _normalize_resort_code(_g(filtros, 'hotel', 'resort'))
        if hotel != 'all_resorts':
            where_clauses.append("unaccent(lower(hotel)) LIKE unaccent(lower(%s))")
            params.append(f"%{hotel}%")

    if _g(filtros, 'destinatario', 'nome', 'emocionador', 'employee'):
        recipient = _g(filtros, 'destinatario', 'nome', 'emocionador', 'employee')
        where_clauses.append("unaccent(lower(destinatario)) LIKE unaccent(lower(%s))")
        params.append(f"%{recipient}%")
    
    months_tuple = _normalize_multiple_months(_g(filtros, 'mes'))
    if months_tuple:
        months_placeholder = ", ".join(["%s"] * len(months_tuple))
        where_clauses.append(f"mes IN ({months_placeholder})")
        params.extend(months_tuple)
        
    where_sql = "WHERE " + " AND ".join(where_clauses)
    
    base_query = f"""
        WITH AggregatedCount AS (
            SELECT
                ano,
                destinatario,
                cr,
                STRING_AGG(DISTINCT hotel::text, ', ') AS hotel,
                COUNT(*) AS total_ocorrencias,
                STRING_AGG(DISTINCT mes::text, ', ' ORDER BY mes::text) AS meses_ocorrencias
            FROM "{TABLE_SENTIMENT_SURVEYS}"
            {where_sql}
            GROUP BY ano, destinatario, cr
        ),
        GlobalRanking AS (
            SELECT
                *,
                ROW_NUMBER() OVER(PARTITION BY ano ORDER BY total_ocorrencias DESC, destinatario ASC) as rank_num
            FROM AggregatedCount
        )
    """

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        count_query = f"{base_query} SELECT COUNT(*) FROM GlobalRanking;"
        cur.execute(count_query, tuple(params))
        total_records = cur.fetchone()[0] or 0

        data_query = f"""
            {base_query}
            SELECT ano, rank_num, destinatario, cr, hotel, total_ocorrencias, meses_ocorrencias
            FROM GlobalRanking
            ORDER BY rank_num ASC
            LIMIT %s OFFSET %s;
        """
        
        final_limit = 5 if not _g(filtros, 'destinatario', 'nome', 'emocionador', 'employee') else 100
        final_params = tuple(params + [final_limit, 0])
        
        cur.execute(data_query, final_params)
        
        db_columns = [desc[0] for desc in cur.description]
        formatted_columns = [COLUMN_NAME_MAP_SENTIMENT.get(c, c) for c in db_columns]
        data = [dict(zip(formatted_columns, row)) for row in cur.fetchall()]
        
        return data, total_records

    except Exception as e:
        print(f"Erro ao executar a consulta de ranking do Felicitômetro: {e}")
        traceback.print_exc()
        return [], 0
    finally:
        if conn:
            conn.close()
