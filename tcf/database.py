import psycopg2
from urllib.parse import urlparse
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DOMAIN_B_DATABASE_URL_WRITER")

def conecta_db():

    if not DATABASE_URL:
        raise ValueError("A variável de ambiente 'DOMAIN_B_DATABASE_URL_WRITER' não foi encontrada ou está vazia.")

    result = urlparse(DATABASE_URL)
    return psycopg2.connect(
        dbname=result.path[1:],
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port
    )

def carrega_dados_existente(conn, tabela):
    cursor = conn.cursor()
    try:
        cursor.execute(f'SELECT * FROM "{tabela}"')
        colunas = [desc[0] for desc in cursor.description]
        dados = [list(linha) for linha in cursor.fetchall()]
        return {"cabecalhos": colunas, "linhas": dados}
    finally:
        cursor.close()
