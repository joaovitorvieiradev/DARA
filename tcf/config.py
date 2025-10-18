import os
import json
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DOMAIN_B_DATABASE_URL_READER", "")
API_TOKEN = os.getenv("DOMAIN_B_API_TOKEN", "")

sheets_json_str = os.getenv("DOMAIN_B_SHEETS_JSON", "[]")
excel_files_json_str = os.getenv("DOMAIN_B_EXCEL_FILES_JSON", "[]")

try:
    SHEETS = json.loads(sheets_json_str)
    EXCEL_FILES = json.loads(excel_files_json_str)
except json.JSONDecodeError:
    print("ERRO CRÍTICO: Formato JSON inválido nas variáveis de ambiente de planilhas/arquivos para DOMAIN_B.")
    SHEETS = []
    EXCEL_FILES = []

DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "t")
