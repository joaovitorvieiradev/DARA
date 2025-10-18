import re
import time
import random
import unicodedata
import traceback
from gspread.exceptions import APIError
import tcf.google_client as google_client
import tcf.database as database
import tcf.sincronizador_logica as sincronizador_logica
from tcf.config import PLANILHAS
from tcf.config import PLANILHAS, ARQUIVOS_EXCEL

INCLUIR_ABAS_REGEX = None  
EXCLUIR_ABAS_REGEX = None  

def normaliza_nome(nome: str) -> str:
    nome = nome.strip().lower()
    nome = unicodedata.normalize("NFD", nome)
    nome = "".join(c for c in nome if unicodedata.category(c) != "Mn")
    return nome.replace(" ", "").replace("-", "").replace("_", "")

def _aba_elegivel(titulo: str) -> bool:
    if INCLUIR_ABAS_REGEX and not re.search(INCLUIR_ABAS_REGEX, titulo):
        return False
    if EXCLUIR_ABAS_REGEX and re.search(EXCLUIR_ABAS_REGEX, titulo):
        return False
    return True

def retry_open_by_key(gsp, plan_id: str, max_attempts: int = 6, base: float = 1.5):
    """
    Abre a planilha com backoff exponencial + jitter para lidar com 5xx (ex.: 503).
    """
    attempt = 1
    last_exc = None
    while attempt <= max_attempts:
        try:
            return gsp.open_by_key(plan_id)
        except APIError as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code and 500 <= code < 600:
                sleep_s = min((base ** attempt) + random.uniform(0, 0.8), 30.0)
                print(f"[RETRY] open_by_key({plan_id}) -> {code}. Tentativa {attempt}/{max_attempts}. Aguardando {sleep_s:.1f}s…")
                time.sleep(sleep_s)
                attempt += 1
                last_exc = e
                continue
            raise
        except Exception as e:
            last_exc = e
            sleep_s = min((base ** attempt) + random.uniform(0, 0.8), 30.0)
            print(f"[RETRY] open_by_key({plan_id}) erro inesperado. Tentativa {attempt}/{max_attempts}. Aguardando {sleep_s:.1f}s…")
            time.sleep(sleep_s)
            attempt += 1
    if last_exc:
        raise last_exc

def main():
    print("==== [SYNC] DOMAIN_B ====")
    print("[MAIN] Sincronização DOMAIN_B — Lógica unificada via prefixo")
    try:
        time.sleep(random.uniform(0, 1.5))

        # --- [BLOCO 1/2] Sincronizando Google Sheets ---
        print("\n--- [BLOCO 1/2] Sincronizando Google Sheets ---")
        gsp = google_client.get_gspread_client()
        sheets_pesados = {}

        for item in PLANILHAS:
            plan_id = item["id"]
            tabela_destino = item["prefix"] # <-- O nome da tabela vem do prefixo

            try:
                print(f"\n[PLANILHA] {plan_id} — Processando...")
                plan = retry_open_by_key(gsp, plan_id)
                
                # Pega a primeira (e única) aba da planilha, sem se preocupar com o nome.
                aba_obj = plan.get_worksheet(0) 
                
                print("="*100)

                print(f"🔄 Aba '{aba_obj.title}' → Tabela '{tabela_destino}'")

                cfg = type(
                    "config", (), {
                        "ID_PLANILHA": plan_id,
                        "DOMAIN_B_TAB_NAME": aba_obj.title, # Passa o título da aba que ele encontrou
                        "TABELA_DESTINO": tabela_destino, # Usa o prefix do config como destino
                        "ZERAR_TIMEOUT_COPY": tabela_destino in sheets_pesados,
                    })
                sincronizador_logica.sync_sheets_data(gsp, cfg, database)
            except Exception as e:
                print(f"[ERRO] Falha ao sincronizar a planilha '{plan_id}':")
                traceback.print_exc()

        print("\n--- [BLOCO 1/2] Sincronização Google Sheets Finalizada ---")

        # --- [BLOCO 2/2] Sincronizando Arquivos Excel ---
        print("\n--- [BLOCO 2/2] Sincronizando Arquivos Excel ---")
        drive_service = google_client.get_drive_service()
        excel_pesados = {}

        for item in ARQUIVOS_EXCEL:
            try:
                cfg = type("config", (), {
                    "ID_ARQUIVO": item["id"],
                    "TABELA_DESTINO": item["prefix"],
                    "ZERAR_TIMEOUT_COPY": item["prefix"] in excel_pesados,
                })
                sincronizador_logica.sync_excel_data(drive_service, cfg, database)
            except Exception as e:
                print(f"[ERRO] Falha ao sincronizar o arquivo Excel ID '{item['id']}':")
                traceback.print_exc()

        print("\n--- [BLOCO 2/2] Sincronização de Arquivos Excel Finalizada ---")

        print("\n✅ [MAIN] Sincronização DOMAIN_B finalizada!")

    except Exception:
        print("\n[ERRO] Falha geral na sincronização (DOMAIN_B):")
        traceback.print_exc()

if __name__ == "__main__":
    main()
