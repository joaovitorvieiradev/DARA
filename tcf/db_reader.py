import psycopg2
from urllib.parse import urlparse
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL_READER = os.getenv("DOMAIN_B_DATABASE_URL_READER")

def get_db_connection():
    """
    Retorna uma conexão de banco de dados SOMENTE LEITURA para as ferramentas de análise da API.
    """
    if not DATABASE_URL_READER:
        raise ConnectionError("A variável de ambiente 'DOMAIN_B_DATABASE_URL_READER' não foi encontrada.")
    
    try:

        result = urlparse(DATABASE_URL_READER)
        
        return psycopg2.connect(
            dbname=result.path[1:],
            user=result.username,
            password=result.password,
            host=result.hostname,
            port=result.port
        )
    except psycopg2.OperationalError as e:
        # Lança um erro mais claro para a API, caso a conexão falhe
        raise ConnectionError(f"Falha ao conectar ao banco de dados de leitura: {e}")
