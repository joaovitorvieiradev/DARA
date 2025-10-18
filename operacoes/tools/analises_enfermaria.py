import re
import unicodedata
from typing import List, Dict, Any, Tuple
from operacoes.db_reader import get_db_connection

# =========================================================
# 1. CONSTANTES E MAPAS
# =========================================================

TABLE_MEDICAL_ATTENDANCES = "medical_attendances"
TABLE_DAILY_OCCUPANCY = "daily_occupancy"

RESORT_CODES = ['resort_alpha', 'resort_beta', 'resort_gamma', 'resort_delta', 'resort_epsilon', 'all_resorts']

MAPA_MESES_PARA_NUMEROS = {
    "janeiro": 1, "jan": 1, "fevereiro": 2, "fev": 2, "marco": 3, "março": 3, "mar": 3,
    "abril": 4, "abr": 4, "maio": 5, "mai": 5, "junho": 6, "jun": 6, "julho": 7, "jul": 7,
    "agosto": 8, "ago": 8, "setembro": 9, "set": 9, "outubro": 10, "out": 10,
    "novembro": 11, "nov": 11, "dezembro": 12, "dez": 12
}

# Mapeia nomes de colunas do ETL para a saída da API
COLUMN_NAME_MAP_ATTENDANCES = {
    "id": "id",
    "carimbodedatahora": "timestamp",
    "data": "attendance_date",
    "horario": "attendance_time",
    "hospedeouemocionador": "patient_type",
    "cr": "cost_center",
    "numerodoapartamento": "room_number",
    "nomecompleto": "patient_name",
    "responsavelegraudeparentescomenor": "guardian_minor",
    "ocorrenciaqueixa": "chief_complaint",
    "partedocorpodosintoma": "affected_body_part",
    "pressaoarterial": "blood_pressure",
    "frequenciacardiaca": "heart_rate",
    "frequenciarespiratoria": "respiratory_rate",
    "saturacao": "saturation",
    "temperatura": "temperature",
    "glicemiacapilar": "capillary_glucose",
    "condutaenfermeiroa": "action_taken",
    "houvetransferenciaparaohospital": "hospital_transfer",
    "qualmeiodetransferencia": "transfer_method",
    "motivodarecusa": "refusal_reason",
    "observacao": "observation",
    "enfermeiroaresponsavel": "attending_nurse",
    "localocorrencia": "occurrence_location",
    "hotel": "resort_code",
    "hospedesreal": "actual_guests_on_day",
    "mes": "month",
    "ano": "year"
}


# =========================================================
# 2. FUNÇÕES AUXILIARES
# =========================================================

def _g(filtros: dict) -> dict:
    """Função interna para normalizar filtros e aceitar aliases."""
    def _norm_key(s: str) -> str:
        s = (s or "").strip().lower()
        s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("utf-8")
        return re.sub(r"[\s_]+", "", s)

    f_normalizado = {_norm_key(k): v for k, v in (filtros or {}).items()}

    alias = {
        "resort": "hotel", "unidade": "hotel", "mês": "mes", "periodo": "mes", "year": "ano", "month": "mes",
        "paciente": "hospedeouemocionador", "tipodepaciente": "hospedeouemocionador", "patienttype": "hospedeouemocionador",
        "queixa": "ocorrenciaqueixa", "sintoma": "ocorrenciaqueixa", "ocorrencia": "ocorrenciaqueixa", "complaint": "ocorrenciaqueixa",
        "enfermeiro": "enfermeiroaresponsavel", "responsavel": "enfermeiroaresponsavel", "nurse": "enfermeiroaresponsavel",
        "partedocorpo": "partedocorpodosintoma", "bodypart": "partedocorpodosintoma",
        "transferencia": "houvetransferenciaparaohospital", "transfer": "houvetransferenciaparaohospital"
    }
    return {alias.get(k, k): v for k, v in f_normalizado.items()}

def _traduzir_periodo_para_numero(valor_periodo: Any) -> Any:
    if not isinstance(valor_periodo, str): return valor_periodo
    try:
        chave_normalizada = valor_periodo.lower().strip().replace('ç', 'c')
        valor_traduzido = MAPA_MESES_PARA_NUMEROS.get(chave_normalizada)
        return int(valor_traduzido if valor_traduzido is not None else chave_normalizada)
    except (ValueError, TypeError, AttributeError):
        return valor_periodo

def _normalizar_nome_hotel(valor_hotel: Any) -> Any:
    if not isinstance(valor_hotel, str): return valor_hotel
    try:
        norm_valor = unicodedata.normalize('NFKD', valor_hotel.lower()).encode('ascii', 'ignore').decode('utf-8')
        for code in RESORT_CODES:
            if code in norm_valor: return code
        return valor_hotel
    except Exception:
        return valor_hotel


# =========================================================
# 3. FUNÇÕES PÚBLICAS DE ANÁLISE
# =========================================================

def list_medical_attendances(filtros: dict, limit: int = 100, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    """
    Busca e lista os registros de atendimentos da enfermagem com base em múltiplos filtros.
    Ideal para obter detalhes brutos de atendimentos específicos.
    """
    f_norm = _g(filtros or {})
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        where_clauses = []
        params = []

        # Mapeamento para filtros que usam LIKE (busca parcial, case-insensitive)
        like_filter_map = {
            'hospedeouemocionador': 'hospedeouemocionador',
            'cr': 'cr',
            'ocorrenciaqueixa': 'ocorrenciaqueixa',
            'partedocorpodosintoma': 'partedocorpodosintoma',
            'enfermeiroaresponsavel': 'enfermeiroaresponsavel',
            'localocorrencia': 'localocorrencia',
            'nomepaciente': 'nomecompleto'
        }

        # --- Lógica para filtros com LIKE ---
        for filter_key, db_col in like_filter_map.items():
            if f_norm.get(filter_key):
                valor = f_norm[filter_key]
                where_clauses.append(f"unaccent(lower({db_col})) LIKE unaccent(lower(%s))")
                params.append(f"%%{valor}%%")
        
        # --- Lógica para filtros com correspondência EXATA ---
        
        # Filtro de Hotel (comportamento exato)
        if f_norm.get('hotel'):
            resort_code = _normalizar_nome_hotel(f_norm['hotel'])
            # A busca por 'all_resorts' não deve ser um filtro SQL, mas sim a ausência dele
            if resort_code != 'all_resorts':
                where_clauses.append(f"unaccent(lower(hotel)) = unaccent(lower(%s))")
                params.append(resort_code)

        if 'houvetransferenciaparaohospital' in f_norm:
            transfer_value = f_norm['houvetransferenciaparaohospital']
            
            # Garante que o valor seja tratado como string ('Sim' ou 'Não')
            if isinstance(transfer_value, bool):
                transfer_value = 'Sim' if transfer_value else 'Não'

            # Compara o valor exato, ignorando acentos e maiúsculas/minúsculas
            where_clauses.append(f"unaccent(lower(houvetransferenciaparaohospital)) = unaccent(lower(%s))")
            params.append(str(transfer_value))

        # --- Filtros de data exatos ---
        if f_norm.get('ano'):
            where_clauses.append("ano = %s")
            params.append(int(f_norm['ano']))
            
        if f_norm.get('mes'):
            where_clauses.append("mes = %s")
            params.append(_traduzir_periodo_para_numero(f_norm['mes']))
            
        if f_norm.get('dia'):
            where_clauses.append("dia = %s")
            params.append(int(f_norm['dia']))

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        # Contagem total de registros
        count_query = f'SELECT COUNT(*) FROM "{TABLE_MEDICAL_ATTENDANCES}" {where_sql}'
        cur.execute(count_query, tuple(params))
        total_registros = cur.fetchone()[0]

        # Query principal
        query = f"""
            SELECT * FROM "{TABLE_MEDICAL_ATTENDANCES}"
            {where_sql}
            ORDER BY data DESC, horario DESC
            LIMIT %s OFFSET %s
        """
        cur.execute(query, tuple(params + [limit, offset]))

        colunas_db = [desc[0] for desc in cur.description]
        colunas_formatadas = [COLUMN_NAME_MAP_ATTENDANCES.get(c, c) for c in colunas_db]
        
        dados = [dict(zip(colunas_formatadas, row)) for row in cur.fetchall()]

        return dados, total_registros

    finally:
        if conn:
            conn.close()

def rank_medical_occurrences(filtros: dict, limit: int = 10, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    """
    Conta e ranqueia as queixas (ocorrências) mais comuns nos atendimentos de enfermagem.
    Útil para identificar os principais motivos de atendimento em um período.
    """
    f_norm = _g(filtros or {})
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        where_clauses = ["ocorrenciaqueixa IS NOT NULL AND ocorrenciaqueixa <> ''"]
        params = []

        if f_norm.get('hotel'):
            resort_code = _normalizar_nome_hotel(f_norm['hotel'])
            if resort_code != 'all_resorts':
                where_clauses.append("unaccent(lower(hotel)) = unaccent(lower(%s))")
                params.append(resort_code)
        if f_norm.get('ano'):
            where_clauses.append("ano = %s")
            params.append(int(f_norm['ano']))
        if f_norm.get('mes'):
            where_clauses.append("mes = %s")
            params.append(_traduzir_periodo_para_numero(f_norm['mes']))

        where_sql = "WHERE " + " AND ".join(where_clauses)

        count_query = f'SELECT COUNT(DISTINCT ocorrenciaqueixa) FROM "{TABLE_MEDICAL_ATTENDANCES}" {where_sql}'
        cur.execute(count_query, tuple(params))
        total_registros = cur.fetchone()[0]

        query = f"""
            SELECT ocorrenciaqueixa, COUNT(*) as total_atendimentos
            FROM "{TABLE_MEDICAL_ATTENDANCES}"
            {where_sql}
            GROUP BY ocorrenciaqueixa
            ORDER BY total_atendimentos DESC
            LIMIT %s OFFSET %s
        """
        cur.execute(query, tuple(params + [limit, offset]))

        dados = [{"chief_complaint": row[0], "total_attendances": row[1]} for row in cur.fetchall()]

        return dados, total_registros

    finally:
        if conn:
            conn.close()

def calculate_attendance_per_guest_index(filtros: dict, limit: int = 1, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    """
    Calcula o índice de atendimentos de enfermagem para Hóspedes (Lazer + Eventos) 
    a cada 100 hóspedes totais no período.
    Filtros de 'hotel', 'ano' e 'mes' são obrigatórios.
    """
    f_norm = _g(filtros or {})
    conn = None

    # Validação de filtros essenciais
    resort_code = _normalizar_nome_hotel(f_norm.get('hotel'))
    year = f_norm.get('ano')
    month = _traduzir_periodo_para_numero(f_norm.get('mes'))

    if not all([resort_code, year, month]) or resort_code == 'all_resorts':
        raise ValueError("Os filtros 'hotel' (específico), 'ano' e 'mes' são obrigatórios para esta análise.")

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Contar atendimentos para hóspedes de Lazer e Eventos
        attendance_params = [resort_code, int(year), int(month)]
        
        query_attendances = f"""
            SELECT COUNT(*)
            FROM "{TABLE_MEDICAL_ATTENDANCES}"
            WHERE unaccent(lower(hotel)) = unaccent(lower(%s))
              AND ano = %s
              AND mes = %s
              AND (
                  unaccent(lower(hospedeouemocionador)) LIKE '%%lazer%%'
                  OR unaccent(lower(hospedeouemocionador)) LIKE '%%eventos%%'
              )
        """
        cur.execute(query_attendances, tuple(attendance_params))
        total_attendances_guests = cur.fetchone()[0]

        # Buscar o total de hóspedes do mês da tabela de ocupação
        guest_params = [resort_code, int(year), int(month)]
        query_guests = f"""
            SELECT SUM(hosptotal)
            FROM "{TABLE_DAILY_OCCUPANCY}"
            WHERE unaccent(lower(resort)) = unaccent(lower(%s))
              AND ano = %s
              AND mes = %s
        """
        cur.execute(query_guests, tuple(guest_params))
        total_guests_result = cur.fetchone()
        total_guests = total_guests_result[0] if total_guests_result and total_guests_result[0] is not None else 0

        # Calcular o índice
        index = (total_attendances_guests / total_guests) * 100 if total_guests > 0 else 0

        # Montar o resultado
        resultado = {
            "resort_code": resort_code,
            "year": int(year),
            "month": int(month),
            "total_attendances_leisure_events_guests": total_attendances_guests,
            "total_guests_in_month": int(total_guests),
            "attendance_per_100_guests_index": round(index, 2)
        }

        return [resultado], 1

    except ValueError as ve:
        raise ve
    finally:
        if conn:
            conn.close()

def count_attendances_by_patient_type(filtros: dict, limit: int = 10, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    """
    Detalha e conta os atendimentos de enfermagem, agrupando por tipo de paciente 
    (Hóspedes a lazer, Emocionadores, etc.) e adiciona uma linha com o total geral.
    Todos os filtros (hotel, ano, mes, cr) são opcionais.
    """
    f_norm = _g(filtros or {})
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        where_clauses = ["hospedeouemocionador IS NOT NULL AND hospedeouemocionador <> ''"]
        params = []

        if f_norm.get('hotel'):
            resort_code = _normalizar_nome_hotel(f_norm['hotel'])
            if resort_code != 'all_resorts':
                where_clauses.append("unaccent(lower(hotel)) = unaccent(lower(%s))")
                params.append(resort_code)
        
        if f_norm.get('ano'):
            where_clauses.append("ano = %s")
            params.append(int(f_norm['ano']))
        
        if f_norm.get('mes'):
            where_clauses.append("mes = %s")
            params.append(_traduzir_periodo_para_numero(f_norm['mes']))
            
        if f_norm.get('dia'):
            where_clauses.append("dia = %s")
            params.append(int(f_norm['dia']))

        if f_norm.get('cr'):
            where_clauses.append("unaccent(lower(cr)) LIKE unaccent(lower(%s))")
            params.append(f"%%{f_norm['cr']}%%")

        where_sql = "WHERE " + " AND ".join(where_clauses)

        # Contagem de grupos distintos para a paginação
        count_query = f'SELECT COUNT(DISTINCT hospedeouemocionador) FROM "{TABLE_MEDICAL_ATTENDANCES}" {where_sql}'
        cur.execute(count_query, tuple(params))
        total_registros = cur.fetchone()[0]

        # Consulta principal que agrupa e conta
        query = f"""
            SELECT hospedeouemocionador, COUNT(*) as total_atendimentos
            FROM "{TABLE_MEDICAL_ATTENDANCES}"
            {where_sql}
            GROUP BY hospedeouemocionador
            ORDER BY total_atendimentos DESC
            LIMIT %s OFFSET %s
        """
        cur.execute(query, tuple(params + [limit, offset]))

        dados = [{"patient_type": row[0], "total_attendances": row[1]} for row in cur.fetchall()]

        if offset == 0 and dados:
            
            total_query = f"""
                SELECT COUNT(*) 
                FROM "{TABLE_MEDICAL_ATTENDANCES}"
                {where_sql}
            """
            cur.execute(total_query, tuple(params))
            total_geral = cur.fetchone()[0]
            
            # Adiciona a linha de total ao final da lista de dados
            dados.append({"patient_type": "Total", "total_attendances": total_geral})

        return dados, total_registros

    finally:
        if conn:
            conn.close()

