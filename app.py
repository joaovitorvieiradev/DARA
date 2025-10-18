from flask import Flask, request, jsonify, render_template
import traceback
from functools import wraps
import math
import webbrowser
import threading
import yaml
import os

# =======================================
# IMPORTAÇÕES DOS MÓDULOS DE DOMÍNIO
# =======================================

    # =======================================
    #               DOMAIN A
    # =======================================
# Importa as funções de análise de Indicadores
from operacoes.tools.analises_indicadores import (
    get_closed_period_indicators
)

# Importa as funções de análise de Ocupação
from operacoes.tools.analises_ocupacao import (
    list_daily_occupancy,
    summarize_guests_by_month,
    calculate_complaint_per_guest_index
)
# Importa as funções de análise de Reclamações
from operacoes.tools.analises_reclamacoes import(
    list_guest_feedback,
    count_feedback_by_type,
    rank_by_keyword,
    search_feedback_by_keyword

)

#importa as funções de analises de receita extra
from operacoes.tools.analises_receita_extra import (
    list_extra_revenue_records,
    calculate_revenue_share,
    compare_extra_revenue_per_guest,
    analyze_item_sales
)
#Importa as funções de analises de enfermaria
from operacoes.tools.analises_enfermaria import (
    list_medical_attendances,
    rank_medical_occurrences,
    calculate_attendance_per_guest_index,
    count_attendances_by_patient_type,
)

    # =======================================
    #               DOMAIN B
    # =======================================

# Importa as funções de análise de banco de horas
from tcf.tools.analise_banco_horas import (
    get_employee_overtime_balance,
    get_department_overtime_balance
)

# Importa as funções de análise de Felicitometro
from tcf.tools.analises_felicitometro import (
    get_resort_adherence,
    get_department_adherence,
    get_survey_status,
    rank_by_survey_status,
    
)


# ==============================
# CONSOLIDAÇÃO E MAPEAMENTO
# ==============================

# --- Funções Auxiliares Centralizadas ---
def _executor(func, filtros):
    """
    Casca de execução flexível:
    - aceita retorno (dados, total_registros) OU (dados, total_registros, dados_ate)
    - padroniza paginação e insere 'dados_ate' no topo quando disponível
    """
    try:
        nome_analise = func.__name__

        limit = int(filtros.pop('limit', 50))
        page = int(filtros.pop('page', 1))
        offset = (page - 1) * limit

        resultado = func(filtros, limit, offset)

        # compatível com (dados, total_registros) e (dados, total_registros, dados_ate)
        if isinstance(resultado, (tuple, list)):
            if len(resultado) == 3:
                dados, total_registros, dados_ate = resultado
            elif len(resultado) == 2:
                dados, total_registros = resultado
                dados_ate = None
            else:
                raise ValueError(f"Retorno inesperado de {nome_analise}: {type(resultado)} com len={len(resultado)}")
        else:
            raise ValueError(f"Retorno inesperado de {nome_analise}: {type(resultado)}")

        total_paginas = math.ceil(total_registros / limit) if limit > 0 else 1

        resposta = {
            "analysis_executed": nome_analise,
            "filters_used": filtros,
            "data": dados,
            "pagination": {
                "page": page,
                "limit": limit,
                "total_records": total_registros,
                "total_pages": total_paginas
            }
        }
        if dados_ate:
            resposta["data_until"] = dados_ate

        return resposta

    except ValueError as ve:
        return {"error": str(ve)}
    except Exception as e:
        print(f"ERRO ao executar {func.__name__}: {traceback.format_exc()}")
        return {"error": f"Erro interno crítico ao processar a análise: {str(e)}"}


# --- Motores de Análise ---
ENGINE_DOMAIN_A = {
    # Análises de Ocupação
    "list_daily_occupancy": lambda f: _executor(list_daily_occupancy, f),
    "summarize_guests_by_month": lambda f: _executor(summarize_guests_by_month, f),
    "calculate_complaint_per_guest_index": lambda f: _executor(calculate_complaint_per_guest_index, f),

    # Análises de Reclamações
    "list_guest_feedback": lambda f: _executor(list_guest_feedback, f),
    "count_feedback_by_type": lambda f: _executor(count_feedback_by_type, f),
    "rank_by_keyword": lambda f: _executor(rank_by_keyword, f),
    "search_feedback_by_keyword": lambda f: _executor(search_feedback_by_keyword, f),

    # Análises de Indicadores
    "get_closed_period_indicators": lambda f: _executor(get_closed_period_indicators, f),

    #analises de Receita Extra
    "list_extra_revenue_records": lambda f: _executor(list_extra_revenue_records, f),
    "compare_extra_revenue_per_guest": lambda f: _executor(compare_extra_revenue_per_guest, f),
    "calculate_revenue_share": lambda f: _executor(calculate_revenue_share, f),    
    "analyze_item_sales": lambda f: _executor(analyze_item_sales, f),

    # Análises de Enfermaria
    "list_medical_attendances": lambda f: _executor(list_medical_attendances, f),
    "rank_medical_occurrences": lambda f: _executor(rank_medical_occurrences, f),
    "calculate_attendance_per_guest_index": lambda f: _executor(calculate_attendance_per_guest_index, f),
    "count_attendances_by_patient_type": lambda f: _executor(count_attendances_by_patient_type, f),

}


ENGINE_DOMAIN_B = {

    # Análises de Banco de horas
    "get_employee_overtime_balance": lambda f: _executor(get_employee_overtime_balance, f),
    "get_department_overtime_balance": lambda f: _executor(get_department_overtime_balance, f),

    # Analises Felicitometro
    "get_resort_adherence": lambda f: _executor(get_resort_adherence, f),
    "get_department_adherence": lambda f: _executor(get_department_adherence, f),
    "get_survey_status": lambda f: _executor(get_survey_status, f),    
    "rank_by_survey_status": lambda f: _executor(rank_by_survey_status, f), 
}



# Tokens de API
from operacoes.config import API_TOKEN as API_TOKEN_DOMAIN_A
from tcf.config import API_TOKEN as API_TOKEN_DOMAIN_B

app = Flask(__name__)

# --- Configuração Central dos Domínios ---
DOMAINS = {
    "domain_a": {
        "token": API_TOKEN_DOMAIN_A,
        "engine": ENGINE_DOMAIN_A,
    },
    "domain_b": {
        "token": API_TOKEN_DOMAIN_B,
        "engine": ENGINE_DOMAIN_B,
    },
}

# --- Middleware de Autenticação ---
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.path == '/test':
            return f(*args, **kwargs)

        domain = request.path.split('/')[1].lower() if request.path.count('/') > 1 else None
        
        if not domain or domain not in DOMAINS:
            if request.path == '/':
                return f(*args, **kwargs)
            return jsonify({"error": "Domínio inválido na URL."}), 404

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({"error": "Cabeçalho de autorização ausente ou mal formatado. Use 'Bearer <token>'"}), 401

        req_token = auth_header.split(" ")[1]
        correct_token = DOMAINS[domain]["token"]

        if req_token != correct_token:
            return jsonify({"error": "Token inválido ou não autorizado para este domínio."}), 401
        
        return f(*args, **kwargs)
    return decorated

# --- Rotas da API ---
@app.route("/")
def health():
    return {"status": "ok"}

@app.route("/test")
def test_harness():
    """Serve a página de testes local."""
    spec_paths = {}
    try:
        with open('openapi.yaml', 'r', encoding='utf-8') as f:
            spec = yaml.safe_load(f)
            spec_paths = spec.get('paths', {})
    except FileNotFoundError:
        print("AVISO: Arquivo 'openapi.yaml' não encontrado. Os parâmetros não serão gerados dinamicamente.")
    except Exception as e:
        print(f"AVISO: Erro ao ler 'openapi.yaml': {e}")

    all_tools = {
        "domain_a": sorted(list(ENGINE_DOMAIN_A.keys())),
        "domain_b": sorted(list(ENGINE_DOMAIN_B.keys()))
    }
    
    return render_template(
        'test_harness.html', 
        all_tools=all_tools,
        spec_paths=spec_paths
    )


@app.route("/<domain>/analise/<analysis_name>", methods=['GET'])
@token_required
def execute_analysis(domain, analysis_name):
    filtros = request.args.to_dict()
    
    norm_domain = domain.lower()
    analysis_engine = DOMAINS[norm_domain].get("engine")
    
    if not analysis_engine or analysis_name not in analysis_engine:
        return jsonify({"error": f"Análise '{analysis_name}' não encontrada no domínio '{domain}'."}), 404

    try:
        analysis_function = analysis_engine[analysis_name]
        result = analysis_function(filtros)
        
        if "error" in result:
            return jsonify(result), 400
            
        return jsonify(result)
    except Exception as e:
        print(f"[ERRO FATAL NA ANÁLISE] {traceback.format_exc()}")
        return jsonify({"error": f"Erro interno crítico ao processar a análise: {str(e)}"}), 500

# --- Execução da Aplicação local---
if __name__ == "__main__":
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
            def open_browser():
                webbrowser.open_new("http://127.0.0.1:10000/test")

            print(">>> Iniciando servidor local da DARA...")
            print(">>> A página de testes abrirá no seu navegador em instantes.")
            threading.Timer(1, open_browser).start()

    app.run(host="0.0.0.0", port=10000, debug=True)
