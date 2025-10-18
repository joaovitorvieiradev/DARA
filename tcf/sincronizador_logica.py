import re
import hashlib
import unicodedata
import traceback
import time
import io
import csv
from collections import OrderedDict
import pandas as pd
from googleapiclient.http import MediaIoBaseDownload
from itertools import chain

# =============================
# Utilidades de normalização
# =============================

def _rm_accents(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c))

def normaliza_coluna(nome: str) -> str:
    """Cabeçalho: sem acento, sem espaço, minúsculo."""
    nome = (nome or "").strip().lower()
    nome = _rm_accents(nome)
    nome = nome.replace(" ", "")
    nome = re.sub(r"[^a-z0-9]", "", nome)
    return nome

# ===============================
# Dedupl de colunas + limpeza
# ===============================

def remove_colunas_duplicadas_normalizando(cabecalhos_raw, linhas):
    """Remove cabeçalhos duplicados após normalização (mantém a 1ª ocorrência)."""
    colunas_norm = []
    indices_usados = []
    vistos = set()
    for idx, nome_original in enumerate(cabecalhos_raw):
        nome_norm = normaliza_coluna(nome_original)
        if nome_norm not in vistos:
            vistos.add(nome_norm)
            colunas_norm.append(nome_norm)
            indices_usados.append(idx)
        else:
            print(f"[WARN] Coluna duplicada ignorada (após normalizar): '{nome_original}' -> '{nome_norm}'")
    linhas_filtradas = [
        [linha[i] if i < len(linha) else "" for i in indices_usados]
        for linha in linhas
    ]
    return colunas_norm, linhas_filtradas

# ========================
# Inferência de tipos (Lógica aprimorada)
# ========================

def parece_numero(val: str):
    return bool(re.fullmatch(r"\s*[-+]?\d+([.,]\d*)?\s*", str(val)))

def inferir_tipos(cabecalhos, linhas):
    print(f"[TIPAGEM] Inferindo tipos de {len(cabecalhos)} colunas com {len(linhas)} linhas...")
    tipos = []
    for i in range(len(cabecalhos)):
        is_real = False
        is_text = False
        for linha in linhas:
            if i >= len(linha):
                continue
            val = str(linha[i]).strip()
            if val == "":
                continue

            if not parece_numero(val):
                is_text = True
                break

            if "." in val or "," in val:
                is_real = True

        if is_text:
            tipos.append("TEXT")
        elif is_real:
            tipos.append("REAL")
        else:
            tipos.append("INTEGER")

    print(f"[TIPAGEM] Tipos inferidos: {tipos}")
    return tipos

def converte_valor_por_tipo(valor, tipo):
    if valor is None:
        return None
    val = str(valor).strip()
    tipo = tipo.upper()
    if val == "":
        return None if tipo in ("INTEGER", "REAL") else ""

    if tipo == "INTEGER":
        try:
            return int(float(val.replace(",", ".")))
        except (ValueError, TypeError):
            return None
    if tipo == "REAL":
        try:
            return float(val.replace(",", "."))
        except (ValueError, TypeError):
            return None
    return val

# ==================================================
# Leitura robusta
# ==================================================

def _try_get_all_values(worksheet):
    start = time.time()
    dados = worksheet.get_all_values()
    print(f"[DEBUG] get_all_values() levou {time.time() - start:.2f}s")
    return dados

# ==================
# Helpers de banco
# ==================

def _table_exists(cur, schema: str, table: str) -> bool:
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s
        )
    """, (schema, table))
    return cur.fetchone()[0]

# =========================================================
# Pipeline principal (Staging and Swap com lógica de timeout)
# =========================================================

def sync_sheets_data(gspread_client, config, db_module):
    """
    Sincroniza uma aba do Sheets com Postgres usando a estratégia "Staging and Swap".
    Garante que o esquema e os dados estejam 100% espelhados com a origem.
    """
    tab_config = getattr(config, 'DOMAIN_B_TAB_NAME', '?')
    table_config = getattr(config, 'TABELA_DESTINO', '?')
    print(f"\n[SYNC] Iniciando sincronização: Aba '{tab_config}' → Tabela '{table_config}'")
    start_total = time.time()
    conn = None
    cur = None

    try:
        # 1. Leitura dos dados
        planilha = gspread_client.open_by_key(config.ID_PLANILHA)
        aba = planilha.worksheet(config.DOMAIN_B_TAB_NAME)
        dados = _try_get_all_values(aba)
        
        nome_tabela_final = config.TABELA_DESTINO
        
        conn = db_module.conecta_db()
        cur = conn.cursor()

        # Caso especial: Se a planilha estiver vazia, remove a tabela de destino.
        if not dados or len(dados) < 2:
            print(f"[SKIP] Aba '{aba.title}' vazia ou sem dados.")
            if _table_exists(cur, "public", nome_tabela_final):
                print(f"[CLEANUP] Removendo tabela de destino '{nome_tabela_final}'...")
                cur.execute(f'DROP TABLE "{nome_tabela_final}"')
                conn.commit()
                print(f"[OK] Tabela '{nome_tabela_final}' removida.")
            else:
                print(f"[INFO] Tabela '{nome_tabela_final}' já não existe.")
            return

        # 2. Processamento, Normalização e Tipagem
        cabecalhos_raw = dados[0]
        linhas_raw = dados[1:]
        print(f"[READ] {len(cabecalhos_raw)} colunas e {len(linhas_raw)} linhas carregadas.")

        cabecalhos, linhas = remove_colunas_duplicadas_normalizando(cabecalhos_raw, linhas_raw)
        tipos_sem_id = inferir_tipos(cabecalhos, linhas)
        cabecalhos_final = ["id"] + cabecalhos
        tipos_sql = ["TEXT"] + tipos_sem_id
        
        mapa = OrderedDict()
        vazias = 0
        for i, linha in enumerate(linhas):
            linha_completa = (linha + [''] * len(cabecalhos))[:len(cabecalhos)]
            linha_corrigida = [
                converte_valor_por_tipo(valor, tipo)
                for valor, tipo in zip(linha_completa, tipos_sem_id)
            ]
            if all((v is None or str(v) == "") for v in linha_corrigida):
                vazias += 1
                continue
            id_gerado = hashlib.sha256(f"{config.ID_PLANILHA}:{aba.title}:{i+2}".encode("utf-8")).hexdigest()
            mapa[id_gerado] = [id_gerado] + linha_corrigida
        
        if vazias: print(f"[CLEAN] Linhas vazias ignoradas: {vazias}")
        linhas_com_id = list(mapa.values())
        print(f"[PROCESS] {len(linhas_com_id)} linhas válidas para carregar.")

        # 3. Preparação da tabela de Staging
        timestamp = int(time.time())
        tabela_staging = f"{nome_tabela_final}_staging_{timestamp}"
        col_defs = ", ".join([f'"{col}" {tipo}' for col, tipo in zip(cabecalhos_final, tipos_sql)])
        
        print(f"[DB] Criando nova tabela de staging: '{tabela_staging}'")
        cur.execute(f'CREATE TABLE "{tabela_staging}" ({col_defs}, PRIMARY KEY("id"))')

        # 4. Carga de dados para a Staging via COPY
        if linhas_com_id:
            out = io.StringIO()
            num_colunas = len(cabecalhos_final)
            for row in linhas_com_id:
                linha_corrigida = list(row)[:num_colunas]
                linha_corrigida.extend([""] * (num_colunas - len(linha_corrigida)))
                campos = [("" if x is None else str(x)).replace("\\", "\\\\").replace("\t", " ").replace("\r", " ").replace("\n", " ") for x in linha_corrigida]
                out.write("\t".join(campos) + "\n")
            out.seek(0)
            
            colunas_formatadas = ", ".join([f'"{c}"' for c in cabecalhos_final])
            sql_copy = f'COPY "{tabela_staging}" ({colunas_formatadas}) FROM STDIN WITH (FORMAT text, DELIMITER E\'\\t\', NULL \'\')'
            
            if getattr(config, "ZERAR_TIMEOUT_COPY", False):
                print("[DB] Tabela grande detectada pela config. Configurando statement_timeout = 0.")
                cur.execute("SET statement_timeout TO 0")

            t_copy0 = time.time()
            cur.copy_expert(sql_copy, out)
            print(f"[DB] COPY para staging levou: {time.time() - t_copy0:.2f}s")

            if getattr(config, "ZERAR_TIMEOUT_COPY", False):
                print("[DB] Resetando statement_timeout para o padrão (30s).")
                cur.execute("SET statement_timeout TO '30s'")
        
        # 5. Troca Atômica
        print(f"[DB] Executando a troca atômica: '{tabela_staging}' se tornará '{nome_tabela_final}'.")
        cur.execute("BEGIN;")
        cur.execute(f'DROP TABLE IF EXISTS "{nome_tabela_final}";')
        cur.execute(f'ALTER TABLE "{tabela_staging}" RENAME TO "{nome_tabela_final}";')
        cur.execute("COMMIT;")
        print(f"[OK] Troca concluída. Tabela '{nome_tabela_final}' está 100% atualizada.")

        # 6. Validação final
        cur.execute(f'SELECT COUNT(*) FROM "{nome_tabela_final}"')
        final_count = cur.fetchone()[0]
        print(f"[VALIDATION] Tabela final '{nome_tabela_final}' contém {final_count} registros.")
        print(f"--- Sincronização de '{table_config}' finalizada em {time.time() - start_total:.2f}s ---")

    except Exception as e:
        print(f"[ERRO CRÍTICO] Falha ao sincronizar '{tab_config}'. Processo interrompido: {e}")
        traceback.print_exc()
        if conn:
            print("[DB] Revertendo transação (rollback)...")
            conn.rollback()
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
            print("[DB] Conexão com o banco de dados fechada.")




def sync_excel_data(drive_service, config, db_module):
    """
    Sincroniza um arquivo Excel do Drive com Postgres, usando a estratégia de
    Staging and Swap. Esta versão lê o arquivo inteiro na memória e lida com timeouts.
    """
    file_id = config.ID_ARQUIVO
    nome_tabela_final = config.TABELA_DESTINO
    print(f"\n[SYNC-EXCEL] Iniciando: Arquivo ID '{file_id}' → Tabela '{nome_tabela_final}'")
    start_total = time.time()
    conn = None; cur = None

    try:
        # === 1. Download do Arquivo Excel ===
        request = drive_service.files().get_media(fileId=file_id)
        file_buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(file_buffer, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status: print(f"Download {int(status.progress() * 100)}%.")
        file_buffer.seek(0)

        # === 2. Leitura do Arquivo INTEIRO para um DataFrame ===
        print("[PROCESS] Lendo o arquivo Excel completo para a memória...")
        df_completo = pd.read_excel(file_buffer, engine='openpyxl')

        if df_completo.empty:
            print(f"[SKIP] Arquivo Excel ID '{file_id}' está vazio ou sem dados.")
            return

        cabecalhos_raw = df_completo.columns.to_list()
        linhas_raw = df_completo.astype(str).replace({'nan': None, 'NaT': None}).values.tolist()
        
        print(f"[READ] Arquivo completo lido: {len(cabecalhos_raw)} colunas e {len(linhas_raw)} linhas.")

        # === 3. Normalização, Tipagem e Preparação do Banco ===
        cabecalhos, linhas_processadas = remove_colunas_duplicadas_normalizando(cabecalhos_raw, linhas_raw)
        tipos_sem_id = inferir_tipos(cabecalhos, linhas_processadas)
        cabecalhos_final = ["id"] + cabecalhos
        tipos_sql = ["TEXT"] + tipos_sem_id

        conn = db_module.conecta_db()
        cur = conn.cursor()
        timestamp = int(time.time())
        tabela_staging = f"{nome_tabela_final}_staging_{timestamp}"
        col_defs = ", ".join([f'"{col}" {tipo}' for col, tipo in zip(cabecalhos_final, tipos_sql)])
        
        print(f"[DB] Criando nova tabela de staging: '{tabela_staging}'")
        cur.execute(f'CREATE TABLE "{tabela_staging}" ({col_defs}, PRIMARY KEY("id"))')

        # === 4. Processamento e Preparação para Carga ===
        print(f"[PROCESS] Processando {len(linhas_processadas)} linhas para carga...")
        mapa = OrderedDict()
        for j, linha in enumerate(linhas_processadas):
            linha_completa = (linha + [''] * len(cabecalhos))[:len(cabecalhos)]
            linha_corrigida = [converte_valor_por_tipo(valor, tipo) for valor, tipo in zip(linha_completa, tipos_sem_id)]
            if all((v is None or str(v) == "") for v in linha_corrigida): continue
            id_gerado = hashlib.sha256(f"{file_id}:{j}".encode("utf-8")).hexdigest()
            mapa[id_gerado] = [id_gerado] + linha_corrigida
        
        linhas_com_id = list(mapa.values())
        if not linhas_com_id:
            print("[WARN] Nenhuma linha válida encontrada para carregar.")
            return

        out = io.StringIO()
        for row in linhas_com_id:
            campos = [("" if x is None else str(x)).replace("\\", "\\\\").replace("\t", " ").replace("\r", " ").replace("\n", " ") for x in row]
            out.write("\t".join(campos) + "\n")
        out.seek(0)
        
        colunas_formatadas = ", ".join([f'"{c}"' for c in cabecalhos_final])
        sql_copy = f'COPY "{tabela_staging}" ({colunas_formatadas}) FROM STDIN WITH (FORMAT text, DELIMITER E\'\\t\', NULL \'\')'
        
        if getattr(config, "ZERAR_TIMEOUT_COPY", False):
            print("[DB] Tabela grande detectada pela config. Configurando statement_timeout = 0.")
            cur.execute("SET statement_timeout TO 0")

        t_copy0 = time.time()
        cur.copy_expert(sql_copy, out)
        print(f"[DB] Carga de {len(linhas_com_id)} linhas para staging levou {time.time() - t_copy0:.2f}s.")

        if getattr(config, "ZERAR_TIMEOUT_COPY", False):
            print("[DB] Resetando statement_timeout para o padrão (30s).")
            cur.execute("SET statement_timeout TO '30s'")

        # === 5. Troca Atômica ===
        print(f"[DB] Carga finalizada. Executando a troca atômica para '{nome_tabela_final}'.")
        cur.execute("BEGIN;")
        cur.execute(f'DROP TABLE IF EXISTS "{nome_tabela_final}";')
        cur.execute(f'ALTER TABLE "{tabela_staging}" RENAME TO "{nome_tabela_final}";')
        cur.execute("COMMIT;")
        print(f"[OK] Troca concluída.")

        # === 6. Validação final ===
        cur.execute(f'SELECT COUNT(*) FROM "{nome_tabela_final}"')
        print(f"[VALIDATION] Tabela final '{nome_tabela_final}' contém {cur.fetchone()[0]} registros.")
        print(f"--- Sincronização de '{nome_tabela_final}' finalizada em {time.time() - start_total:.2f}s ---")

    except Exception as e:
        print(f"[ERRO CRÍTICO] Falha ao sincronizar arquivo Excel ID '{file_id}'. Processo interrompido: {e}")
        traceback.print_exc()
        if conn: conn.rollback()
    finally:
        if cur: cur.close()
        if conn: conn.close()
        print("[DB] Conexão com o banco de dados fechada.")
