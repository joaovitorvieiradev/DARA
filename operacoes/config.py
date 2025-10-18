import os
import json
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DOMAIN_A_DATABASE_URL_READER", "")
API_TOKEN = os.getenv("DOMAIN_A_API_TOKEN", "")

planilhas_json_str = os.getenv("DOMAIN_A_PLANILHAS_JSON", "[]")
arquivos_excel_json_str = os.getenv("DOMAIN_A_ARQUIVOS_EXCEL_JSON", "[]")

try:
    PLANILHAS = json.loads(planilhas_json_str)
    ARQUIVOS_EXCEL = json.loads(arquivos_excel_json_str)
except json.JSONDecodeError:
    
    print("ERRO CRÍTICO: Formato JSON inválido nas variáveis de ambiente de planilhas/arquivos para DOMAIN_A.")
    PLANILHAS = []
    ARQUIVOS_EXCEL = []

DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "t")
