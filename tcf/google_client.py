import os
import json
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly"
]

def get_gspread_client():
    json_credentials = os.getenv("DOMAIN_B_GOOGLE_CREDENTIALS_JSON")
    if json_credentials is None:
        raise ValueError("Variável de ambiente 'DOMAIN_B_GOOGLE_CREDENTIALS_JSON' não está definida.")

    print("[DEBUG] Trecho inicial do JSON de credencial DOMAIN_B:")
    print(repr(json_credentials[:300]))

    json_credentials = json_credentials.replace('\\\\n', '\\n')

    json_credentials = json_credentials.replace('\r\n', '\n').replace('\r', '\n').replace('\t', '')

    try:
        cred_info = json.loads(json_credentials)
    except Exception as e:
        print("[ERRO] JSON inválido! Veja o início da variável:")
        print(repr(json_credentials[:500]))
        raise e

    creds = Credentials.from_service_account_info(cred_info, scopes=SCOPES)
    return gspread.authorize(creds)


def get_drive_service():
    json_credentials = os.getenv("DOMAIN_B_GOOGLE_CREDENTIALS_JSON")
    if json_credentials is None:
        raise ValueError("Variável de ambiente 'DOMAIN_B_GOOGLE_CREDENTIALS_JSON' não está definida.")
    print("[DEBUG] Trecho inicial do JSON de credencial DOMAIN_B:")
    print(repr(json_credentials[:300]))

    json_credentials = json_credentials.replace('\\\\n', '\\n')

    json_credentials = json_credentials.replace('\r\n', '\n').replace('\r', '\n').replace('\t', '')

    try:
        cred_info = json.loads(json_credentials)
    except Exception as e:
        print("[ERRO] JSON inválido! Veja o início da variável:")
        print(repr(json_credentials[:500]))
        raise e
        
    creds = Credentials.from_service_account_info(cred_info, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)
