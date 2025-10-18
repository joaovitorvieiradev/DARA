import re
import unicodedata
import traceback
from typing import List, Dict, Any, Tuple
from decimal import Decimal, getcontext
from operacoes.db_reader import get_db_connection

# =========================================================
# 1. CONSTANTES E MAPAS
# =========================================================

TABLE_EXTRA_REVENUE = "extra_revenue"
TABLE_DAILY_OCCUPANCY = "daily_occupancy"
TABLE_ACCOMMODATION_REVENUE = "accommodation_revenue"
TABLE_MONTHLY_TARGETS = "monthly_extra_revenue_targets"
TABLE_GUEST_TARGETS = "guest_targets"
TABLE_POS_ITEM_SALES_BASE = "pos_item_sales_"

RESORT_CODES = ['resort_alpha', 'resort_beta', 'resort_gamma', 'resort_delta', 'resort_epsilon', 'all_resorts']

getcontext().prec = 18

COLUMN_NAME_MAP_EXTRA_REVENUE = {
    "id": "id", "resort": "resort_code", "mes": "month", "pdv": "point_of_sale", "categoria": "category",
    "meta": "target", "ano": "year", "data": "date", "hospedes": "guests",
    "vendatotalpdv": "total_pos_sales", "metaano": "year_target", "trimestre": "quarter",
    "semestre": "semester", "metastrimestre": "quarter_targets", "metassemestre": "semester_targets",
    "dia": "day", "hospmeta": "guest_target"
}

MONTH_NAME_TO_NUMBER_MAP = {
    "janeiro": 1, "jan": 1, "fevereiro": 2, "fev": 2, "marco": 3, "março": 3, "mar": 3,
    "abril": 4, "abr": 4, "maio": 5, "mai": 5, "junho": 6, "jun": 6, "julho": 7, "jul": 7,
    "agosto": 8, "ago": 8, "setembro": 9, "set": 9, "outubro": 10, "out": 10,
    "novembro": 11, "nov": 11, "dezembro": 12, "dez": 12
}

# =========================================================
# 2. FUNÇÕES AUXILIARES E UTILITÁRIOS
# =========================================================

def _g(filtros: dict) -> dict:
    """Normaliza as chaves de um dicionário de filtros e aplica aliases."""
    def _norm_key(s: str) -> str:
        s = (s or "").strip().lower()
        s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("utf-8")
        return re.sub(r"[\s_]+", "", s)
    f_normalizado = {_norm_key(k): v for k, v in (filtros or {}).items()}
    alias = {"resort": "hotel", "unidade": "hotel", "mês": "mes", "periodo": "mes"}
    return {alias.get(k, k): v for k, v in f_normalizado.items()}

def _format_sales_value(valor: Any) -> any:
    """
    Formata um valor numérico (int, float, Decimal) para int se não tiver casas decimais,
    ou para float com 2 casas decimais caso contrário.
    """
    if valor is None:
        return 0
    try:
        # A soma no banco pode retornar Decimal, então convertemos para garantir
        valor_decimal = Decimal(valor)
    except Exception:
        return 0

    # Se o valor é, na prática, um inteiro (ex: 150.00), retorna como int
    if valor_decimal == valor_decimal.to_integral_value():
        return int(valor_decimal)
    else:
        return float(round(valor_decimal, 2))

def _normalize_resort_code(resort_value: Any) -> Any:
    """Retorna nome canônico do hotel, incluindo 'all_resorts'."""
    if not isinstance(resort_value, str): return resort_value
    try:
        norm_valor = unicodedata.normalize('NFKD', resort_value.lower()).encode('ascii', 'ignore').decode('utf-8')
        for canonical in RESORT_CODES:
            if canonical in norm_valor: return canonical
        return resort_value
    except Exception: return resort_value

def _translate_period_to_number(period_value: Any) -> Any:
    """Tenta converter um nome de mês (str) para seu número (int)."""
    if not isinstance(period_value, str): return period_value
    try:
        chave_normalizada = period_value.lower().strip().replace('ç', 'c')
        valor_traduzido = MONTH_NAME_TO_NUMBER_MAP.get(chave_normalizada)
        return int(valor_traduzido if valor_traduzido is not None else chave_normalizada)
    except (ValueError, TypeError, AttributeError): return period_value

def _format_column_name(column_name: str, name_map: dict) -> str:
    """Formata o nome da coluna para um padrão snake_case ou usa um mapa."""
    name_lower = column_name.lower()
    return name_map.get(name_lower, name_lower)
    
# =========================================================
# 3. FUNÇÕES PÚBLICAS DE ANÁLISE
# =========================================================

def list_extra_revenue_records(filtros: dict, limit: int = 100, offset: int = 0) -> Tuple[List[dict], int]:
    """Busca e lista os registros diários e brutos da tabela de receita extra."""
    f_norm = _g(filtros or {})
    if not all([f_norm.get("hotel"), f_norm.get("ano"), f_norm.get("mes")]):
        raise ValueError("Os filtros 'hotel', 'ano' e 'mes' são obrigatórios.")

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        where_clauses = ["ano = %s", "mes = %s"]
        params = [int(f_norm.get("ano")), _translate_period_to_number(f_norm.get("mes"))]

        resort_code = _normalize_resort_code(f_norm.get("hotel"))
        if resort_code != 'all_resorts':
            where_clauses.insert(0, "unaccent(lower(resort)) = unaccent(lower(%s))")
            params.insert(0, resort_code)

        if f_norm.get("dia"):
            where_clauses.append("dia = %s")
            params.append(int(f_norm.get("dia")))
        
        where_sql = "WHERE " + " AND ".join(where_clauses)
        
        count_query = f'SELECT COUNT(*) FROM "{TABLE_EXTRA_REVENUE}" {where_sql}'
        cur.execute(count_query, tuple(params))
        total_records = cur.fetchone()[0]

        query = f"""
            SELECT * FROM "{TABLE_EXTRA_REVENUE}" 
            {where_sql} ORDER BY data ASC, dia ASC 
            LIMIT %s OFFSET %s
        """
        cur.execute(query, tuple(params + [limit, offset]))
        columns = [_format_column_name(d[0], COLUMN_NAME_MAP_EXTRA_REVENUE) for d in cur.description]
        data = [dict(zip(columns, row)) for row in cur.fetchall()]
        
        return data, total_records
    finally:
        if conn: conn.close()

def calculate_revenue_share(filtros: dict, limit: int = 100, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    """
    Calcula o percentual consolidado da receita extra sobre a receita de hospedagem
    para o período informado. Suporta um filtro opcional de PDV, que afeta
    apenas o cálculo da receita extra.
    """
    f_norm = _g(filtros or {})
    if not all([f_norm.get("hotel"), f_norm.get("ano"), f_norm.get("mes")]):
        raise ValueError("Os filtros 'hotel', 'ano' e 'mes' são obrigatórios.")

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        resort_code = _normalize_resort_code(f_norm.get('hotel'))
        is_all_resorts = resort_code == 'all_resorts'
        
        month_input = str(f_norm.get('mes'))
        months_list = [int(m.strip()) for m in month_input.split(',') if m.strip().isdigit()] if ',' in month_input else ([_translate_period_to_number(month_input)] if _translate_period_to_number(month_input) else [])
        
        pos_input = str(f_norm.get("pdv", "")).lower()
        pos_list = [p.strip() for p in pos_input.split(',') if p.strip()]

        if not months_list:
            raise ValueError("O filtro 'mes' é obrigatório e deve ser válido.")

        base_where_parts = ["ano = %s"]
        base_params = [int(f_norm.get('ano'))]
        
        if not is_all_resorts:
            base_where_parts.insert(0, "unaccent(lower({hotel_col})) = unaccent(lower(%s))")
            base_params.insert(0, resort_code)

        base_where_parts.append("mes IN %s")
        base_params.append(tuple(months_list))

        accommodation_where_sql = "WHERE " + " AND ".join(base_where_parts).format(hotel_col='hotel')
        cur.execute(f'SELECT SUM(COALESCE(lazer, 0)), SUM(COALESCE(eventos, 0)) FROM "{TABLE_ACCOMMODATION_REVENUE}" {accommodation_where_sql};', tuple(base_params))
        accommodation_res = cur.fetchone()
        total_leisure_accommodation = Decimal(accommodation_res[0] or '0.0')
        total_events_accommodation = Decimal(accommodation_res[1] or '0.0')
        
        extra_rev_where_parts = base_where_parts[:]
        extra_rev_params = base_params[:]
        
        if pos_list:
            extra_rev_where_parts.append("unaccent(lower(pdv)) IN %s")
            extra_rev_params.append(tuple(pos_list))

        extra_rev_sql = "WHERE " + " AND ".join(extra_rev_where_parts).format(hotel_col='resort')
        extra_rev_query = f'SELECT categoria, SUM(COALESCE(vendatotalpdv, 0)) FROM "{TABLE_EXTRA_REVENUE}" {extra_rev_sql} GROUP BY categoria;'
        cur.execute(extra_rev_query, tuple(extra_rev_params))
        
        extra_rev_map = {"Lazer": Decimal('0.0'), "Eventos": Decimal('0.0')}
        for cat, total in cur.fetchall():
            if cat in extra_rev_map: 
                extra_rev_map[cat] = Decimal(total or '0.0')

        formatted_data = []

        leisure_perc = (extra_rev_map["Lazer"] / total_leisure_accommodation * 100) if total_leisure_accommodation > 0 else 0
        formatted_data.append({
            "category": "Leisure", 
            "accommodation_revenue": _format_sales_value(total_leisure_accommodation), 
            "extra_revenue": _format_sales_value(extra_rev_map["Lazer"]), 
            "extra_revenue_share_percentage": round(float(leisure_perc), 2)
        })

        events_perc = (extra_rev_map["Eventos"] / total_events_accommodation * 100) if total_events_accommodation > 0 else 0
        formatted_data.append({
            "category": "Events", 
            "accommodation_revenue": _format_sales_value(total_events_accommodation), 
            "extra_revenue": _format_sales_value(extra_rev_map["Eventos"]), 
            "extra_revenue_share_percentage": round(float(events_perc), 2)
        })

        return formatted_data, len(formatted_data)
    finally:
        if conn: conn.close()

def compare_extra_revenue_per_guest(filtros: dict, limit: int = 100, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    f_norm = _g(filtros or {})
    if not all([f_norm.get("hotel"), f_norm.get("ano"), f_norm.get("mes")]):
        raise ValueError("Os filtros 'hotel', 'ano' e 'mes' são obrigatórios.")

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        hotel_input = str(f_norm.get('hotel', '')).lower()
        resorts_list = [h.strip() for h in hotel_input.split(',') if h.strip()]
        is_all_resorts = 'all_resorts' in resorts_list
        
        month_input = str(f_norm.get('mes'))
        months_list = sorted([int(m.strip()) for m in month_input.split(',') if m.strip().isdigit()] if ',' in month_input else ([_translate_period_to_number(month_input)] if _translate_period_to_number(month_input) else []))
        
        pos_input = str(f_norm.get("pdv", "")).lower()
        pos_list = [p.strip() for p in pos_input.split(',') if p.strip()]

        if not pos_list:
            combined_data = {}
            
            actuals_where_parts = ["ano = %s"]
            actuals_params = [int(f_norm.get('ano'))]
            
            if not is_all_resorts:
                actuals_params.insert(0, tuple(resorts_list))
                actuals_where_parts.insert(0, "unaccent(lower(resort)) IN %s")
            
            if months_list:
                actuals_params.append(tuple(months_list))
                actuals_where_parts.append("mes IN %s")

            days_list = [int(d.strip()) for d in str(f_norm.get("dia", "")).split(',') if d.strip().isdigit()]
            if days_list:
                actuals_params.append(tuple(days_list))
                actuals_where_parts.append("dia IN %s")
            
            occupancy_where_sql = "WHERE " + " AND ".join(actuals_where_parts)
            cur.execute(f'SELECT SUM(COALESCE(lazer, 0)), SUM(COALESCE(eventos, 0)) FROM "{TABLE_DAILY_OCCUPANCY}" {occupancy_where_sql};', tuple(actuals_params))
            guest_res = cur.fetchone()
            if guest_res:
                combined_data["Lazer"] = {"actual_guests": int(guest_res[0] or 0)}
                combined_data["Eventos"] = {"actual_guests": int(guest_res[1] or 0)}

            revenue_where_sql = "WHERE " + " AND ".join(actuals_where_parts)
            cur.execute(f'SELECT categoria, SUM(COALESCE(vendatotalpdv, 0)) as total_venda FROM "{TABLE_EXTRA_REVENUE}" {revenue_where_sql} GROUP BY categoria;', tuple(actuals_params))
            for category, total_sales in cur.fetchall():
                if category in combined_data:
                    combined_data[category]["total_revenue_actual"] = _format_sales_value(total_sales)

            target_query_params = {'ano': int(f_norm.get('ano'))}
            target_where_cte = ["t.ano = %(ano)s"]
            target_where_join = ["hm.ano = %(ano)s"]

            if not is_all_resorts:
                target_where_cte.append("unaccent(lower(t.resort)) IN %(hoteis)s")
                target_where_join.append("unaccent(lower(hm.resort)) IN %(hoteis)s")
                target_query_params['hoteis'] = tuple(resorts_list)
            
            if months_list:
                target_where_cte.append("t.mes IN %(meses)s")
                target_where_join.append("hm.mes IN %(meses)s")
                target_query_params['meses'] = tuple(months_list)

            target_query = f"""
                WITH MonthlyTargetsAggregated AS (
                    SELECT mes, resort, categoria, SUM(CAST(meta AS NUMERIC)) as sum_target_month
                    FROM {TABLE_MONTHLY_TARGETS} t
                    WHERE {" AND ".join(target_where_cte)}
                    GROUP BY mes, resort, categoria
                )
                SELECT
                    mma.categoria,
                    SUM(mma.sum_target_month * hm.hospmeta) as sum_products,
                    SUM(hm.hospmeta) as sum_weights
                FROM MonthlyTargetsAggregated mma
                JOIN {TABLE_GUEST_TARGETS} hm ON mma.mes = hm.mes AND mma.resort = hm.resort AND mma.categoria = hm.categoria
                WHERE {" AND ".join(target_where_join)}
                GROUP BY mma.categoria
            """
            cur.execute(target_query, target_query_params)
            for category, sum_products, sum_weights in cur.fetchall():
                final_target = Decimal(sum_products) / Decimal(sum_weights) if sum_weights and sum_weights > 0 else 0
                combined_data.setdefault(category, {})["revenue_per_guest_target"] = _format_sales_value(final_target)

            formatted_data = []
            for category in sorted(combined_data.keys()):
                cat_data = combined_data[category]
                actual_revenue = cat_data.get("total_revenue_actual", 0)
                actual_guests = cat_data.get("actual_guests", 0)
                actual_per_guest = _format_sales_value(Decimal(actual_revenue) / Decimal(actual_guests) if actual_guests > 0 else 0)
                
                formatted_data.append({
                    "category": category,
                    "revenue_per_guest_actual": actual_per_guest,
                    "revenue_per_guest_target": cat_data.get("revenue_per_guest_target", 0),
                })
            return formatted_data, len(formatted_data)

        else:
            params = {'ano': int(f_norm.get('ano'))}
            where_parts = ["ano = %(ano)s"]
            if not is_all_resorts:
                where_parts.append("unaccent(lower(resort)) IN %(hoteis)s")
                params['hoteis'] = tuple(resorts_list)
            if months_list:
                where_parts.append("mes IN %(meses)s")
                params['meses'] = tuple(months_list)

            guest_query = f"""
                SELECT mes, SUM(COALESCE(lazer, 0)), SUM(COALESCE(eventos, 0))
                FROM {TABLE_DAILY_OCCUPANCY} WHERE {" AND ".join(where_parts)} GROUP BY mes
            """
            cur.execute(guest_query, params)
            guest_map = { m: {'Lazer': Decimal(lg), 'Eventos': Decimal(eg)} for m, lg, eg in cur.fetchall() }

            revenue_where_parts = where_parts + ["unaccent(lower(pdv)) IN %(pdvs)s"]
            revenue_params = {**params, 'pdvs': tuple(pos_list)}
            revenue_query = f"""
                SELECT mes, pdv, categoria, SUM(COALESCE(vendatotalpdv, 0))
                FROM {TABLE_EXTRA_REVENUE} WHERE {" AND ".join(revenue_where_parts)} GROUP BY mes, pdv, categoria
            """
            cur.execute(revenue_query, revenue_params)
            sales_data = cur.fetchall()

            pos_results = {}
            for month, pos, category, sales in sales_data:
                pos_cat_key = (pos.title(), category)
                monthly_guests = guest_map.get(month, {}).get(category)
                if monthly_guests and monthly_guests > 0:
                    pos_entry = pos_results.setdefault(pos_cat_key, {'monthly_data': {}})
                    pos_entry['monthly_data'][month] = {'sales': Decimal(sales), 'guests': monthly_guests}
            
            formatted_data = []
            for (pos, category), pos_data in sorted(pos_results.items()):
                final_row = {"point_of_sale": pos, "category": category}
                total_sales_period = Decimal(0)
                total_guests_period = Decimal(0)

                for month in months_list:
                    month_data = pos_data['monthly_data'].get(month)
                    if month_data:
                        monthly_actual = month_data['sales'] / month_data['guests']
                        final_row[f'actual_month_{month}'] = _format_sales_value(monthly_actual)
                        total_sales_period += month_data['sales']
                        total_guests_period += month_data['guests']
                    else:
                        final_row[f'actual_month_{month}'] = 0
                
                if len(months_list) > 1:
                    total_actual = total_sales_period / total_guests_period if total_guests_period > 0 else 0
                    final_row['total'] = _format_sales_value(total_actual)

                formatted_data.append(final_row)
            
            return formatted_data, len(formatted_data)

    finally:
        if conn: conn.close()


def analyze_item_sales(filtros: dict, limit: int = 10, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    f_norm = _g(filtros or {})

    if not all([f_norm.get("hotel"), f_norm.get("ano"), f_norm.get("mes")]):
        raise ValueError("Os filtros 'hotel', 'ano' e 'mes' são obrigatórios para esta análise.")

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        resort_code = _normalize_resort_code(f_norm.get('hotel'))
        is_all_resorts = resort_code == 'all_resorts'

        try:
            year_param = int(f_norm.get('ano'))
        except ValueError:
            raise ValueError("O filtro 'ano' deve ser um número válido.")

        month_input = str(f_norm.get('mes'))
        months_list = sorted([int(m.strip()) for m in month_input.split(',') if m.strip().isdigit()] if ',' in month_input else ([_translate_period_to_number(month_input)] if _translate_period_to_number(month_input) else []))
        if not months_list:
            raise ValueError("Filtro 'mes' inválido ou não fornecido.")

        day_input = str(f_norm.get("dia", ""))
        days_list = sorted([int(d.strip()) for d in day_input.split(',') if d.strip().isdigit()])

        category_input = str(f_norm.get('categoria', '')).lower()
        guest_column_sql = ""
        sales_categories_list = []

        if 'lazer' in category_input:
            guest_column_sql = 'COALESCE(lazer, 0)'
            sales_categories_list = ['lazer']
        elif 'eventos' in category_input:
            guest_column_sql = 'COALESCE(eventos, 0)'
            sales_categories_list = ['eventos']
        else:
            guest_column_sql = 'COALESCE(lazer, 0) + COALESCE(eventos, 0)'
            sales_categories_list = ['lazer', 'eventos']

        pos_input = str(f_norm.get("pdv", "")).lower()
        pos_list = [p.strip() for p in pos_input.split(',') if p.strip()]

        class_input = str(f_norm.get("classe", "")).lower()
        classes_list = [c.strip() for c in class_input.split(',') if c.strip()]

        order_input = str(f_norm.get('ordenacao', 'maior')).lower()
        order_sql = 'ASC' if order_input == 'menor' else 'DESC'

        TABLE_POS_ITEM_SALES = f"{TABLE_POS_ITEM_SALES_BASE}{year_param}"

        guest_where_parts = ["ano = %s", "mes IN %s"]
        guest_params = [year_param, tuple(months_list)]

        if not is_all_resorts:
            guest_where_parts.insert(0, "unaccent(lower(resort)) = unaccent(lower(%s))")
            guest_params.insert(0, resort_code)

        if days_list:
            guest_where_parts.append("dia IN %s")
            guest_params.append(tuple(days_list))

        guest_where_sql = "WHERE " + " AND ".join(guest_where_parts)
        guest_query = f'SELECT SUM({guest_column_sql}) FROM "{TABLE_DAILY_OCCUPANCY}" {guest_where_sql};'

        cur.execute(guest_query, tuple(guest_params))
        total_guests_result = cur.fetchone()
        total_guests = Decimal(total_guests_result[0] or '0.0')

        if total_guests <= 0:
            return [], 0

        sales_where_parts = [
            "ano = %s",
            "mes IN %s",
            "unaccent(lower(categoria)) IN %s"
        ]
        sales_params = [year_param, tuple(months_list), tuple(sales_categories_list)]

        if not is_all_resorts:
            sales_where_parts.insert(0, "unaccent(lower(hotel)) = unaccent(lower(%s))")
            sales_params.insert(0, resort_code)

        if days_list:
            sales_where_parts.append("dia IN %s")
            sales_params.append(tuple(days_list))

        if pos_list:
            sales_where_parts.append("unaccent(lower(pdv)) IN %s")
            sales_params.append(tuple(pos_list))

        if classes_list:
            sales_where_parts.append("unaccent(lower(classe)) IN %s")
            sales_params.append(tuple(classes_list))

        sales_where_sql = "WHERE " + " AND ".join(sales_where_parts)

        base_sales_query = f"""
            SELECT
                itemcomanda,
                SUM(COALESCE(valorcomanda, 0)) as total_venda,
                SUM(COALESCE(qtdeitemcomanda, 0)) as total_quantidade
            FROM "{TABLE_POS_ITEM_SALES}"
            {sales_where_sql}
            GROUP BY itemcomanda
        """

        paginated_sales_query = f"""
             WITH SalesByItem AS (
                {base_sales_query}
            )
            SELECT
                itemcomanda,
                total_venda,
                total_quantidade
            FROM SalesByItem
            WHERE total_venda > 0
            ORDER BY total_venda {order_sql}
            LIMIT %s OFFSET %s
        """
        paginated_sales_params = sales_params + [limit, offset]

        count_query = f"""
            WITH SalesByItem AS ({base_sales_query})
            SELECT COUNT(*) FROM SalesByItem WHERE total_venda > 0
        """

        cur.execute(count_query, tuple(sales_params))
        total_records_result = cur.fetchone()
        total_records = total_records_result[0] if total_records_result else 0

        cur.execute(paginated_sales_query, tuple(paginated_sales_params))
        raw_data = cur.fetchall()

        formatted_data = []
        if raw_data:
            for row in raw_data:
                item_name = row[0]
                total_item_sales = Decimal(row[1] or '0.0')
                total_item_quantity = int(row[2] or 0)
                sales_per_guest = total_item_sales / total_guests if total_guests > 0 else 0

                formatted_data.append({
                    "item": item_name,
                    "total_quantity": total_item_quantity,
                    "total_sales": _format_sales_value(total_item_sales),
                    "sales_per_guest": _format_sales_value(sales_per_guest)
                })

            formatted_data.sort(key=lambda x: x["sales_per_guest"], reverse=(order_sql == 'DESC'))

        return formatted_data, total_records

    except Exception as e:
        print(f"ERRO em analyze_item_sales: {e}")
        traceback.print_exc()
        if conn: conn.rollback()
        if 'relation' in str(e) and 'does not exist' in str(e):
             raise ValueError(f"A tabela de dados '{TABLE_POS_ITEM_SALES}' para o ano {year_param} não foi encontrada.")
        raise ValueError(f"Erro ao processar análise de itens: {e}")

    finally:
        if conn:
            conn.close()
