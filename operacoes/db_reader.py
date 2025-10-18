import psycopg2
from urllib.parse import urlparse
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL_READER = os.getenv("DOMAIN_A_DATABASE_URL_READER")

def get_db_connection():
    """
    Retorna uma conexão de banco de dados SOMENTE LEITURA para as ferramentas de análise da API.
    """
    if not DATABASE_URL_READER:
        raise ConnectionError("A variável de ambiente 'DOMAIN_A_DATABASE_URL_READER' não foi encontrada.")
    
    try:
        result = urlparse(DATABASE_URL_READER)
        
        conn = psycopg2.connect(
            dbname=result.path[1:],
            user=result.username,
            password=result.password,
            host=result.hostname,
            port=result.port
        )

        # Bloco de verificação simples para garantir que a conexão foi estabelecida
        cursor = conn.cursor()
        cursor.execute('SELECT current_user;')
        db_user = cursor.fetchone()[0]
        cursor.close()

        return conn
        
    except psycopg2.OperationalError as e:
        raise ConnectionError(f"Falha ao conectar ao banco de dados de leitura: {e}")
