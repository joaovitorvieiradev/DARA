<div aling="center">
   
# DARA 

### Dados, Análises, Respostas e Altomações
</div>
Uma API de análise de dados e pipeline ETL construída para Business Intelligence.

---

🏷️ **Tecnologias (Badges)**
```
- Python 3.10
- Flask
- PostgreSQL
- Render
- GitHub Actions
```
---

🎯 **Visão Geral do Projeto**

O DARA foi desenvolvido como uma solução de Business Intelligence para centralizar, processar e analisar dados de negócio de forma automatizada.

Ele é uma solução de back-end completa que:
- Extrai e Carrega (ETL): Busca dados brutos de múltiplas fontes (Google Sheets, Google Drive/Excel) de diferentes departamentos (Operações, TCF).
- Transforma e Armazena (Staging & Swap): Limpa, normaliza, infere tipos e armazena os dados de forma eficiente em um banco PostgreSQL (Supabase).
- Expõe (API): Disponibiliza uma API RESTful segura feita com Flask.
- Automatiza (CI/CD): Usa GitHub Actions para rodar o pipeline ETL diariamente, garantindo dados sempre atualizados.

O DARA serve como “única fonte da verdade” (Single Source of Truth) para os dados da empresa, pronto para integrar com frontends ou agentes de IA.

---

🛠️ **Stack de Tecnologia**

- **Backend:** Python 3.10, Flask
- **Banco de Dados:** PostgreSQL (Supabase)
- **ETL:** Pandas, GSpread, Google Drive API, Psycopg2
- **Deploy:** Render
- **Automação:** GitHub Actions
- **Frontend (Testes):** HTML, CSS, JavaScript

---

✨ **Principais Funcionalidades**

- **Pipeline de ETL “Staging & Swap”:** Atualização atômica de tabelas, garantindo zero downtime.
- **API Multi-Domínio:** Separação de lógicas de negócio por domínio (/operacoes e /tcf).
- **Catálogo de Análises:** Diversos endpoints analíticos (ocupação, banco de horas, clima organizacional, etc).
- **Segurança:** Bearer Tokens e variáveis de ambiente (.env e GitHub Secrets).
- **Ambiente de Testes:** Interface web local (/test) para depuração e validação.

---

🌊 **Fluxo de Dados (Arquitetura)**

[Fontes (Google Sheets/Excel)]
→ [GitHub Actions (Job Diário)]
→ [Script ETL (Python)]
→ [Banco de Dados (Supabase/PostgreSQL)]
→ [API (Flask/Render)]
→ [Cliente (App, Power BI, IA)]

---

🗂 **Estrutura de Pastas**

```
DARA/
├── .github/
│   └── workflows/
│       └── sincroniza.yml      # Job do GitHub Actions (ETL diário)
├── operacoes/
│   ├── tools/                  # Módulos de análise
│   ├── config.py               # Configurações e tokens
│   ├── database.py             # Conexão de escrita
│   ├── db_reader.py            # Conexão de leitura
│   ├── google_client.py        # Cliente de API do Google
│   ├── main.py                 # Orquestrador ETL
│   └── sincronizador_logica.py # Lógica "Staging & Swap"
├── static/
│   └── test_harness/           # HTML/CSS/JS de testes
├── tcf/                        # Estrutura similar à de 'operacoes'
├── templates/
│   └── test_harness.html       # Página de testes
├── .gitignore                  # Arquivos ignorados
├── app.py                      # Servidor Flask
├── requirements.txt            # Dependências
└── sincroniza_github.py        # Script chamado pelo GitHub Actions
```

---

🚀 **Como Executar Localmente**
```
1. Clone o repositório:
   git clone https://github.com/seu-usuario/dara.git
   cd dara

2. Crie e ative o ambiente virtual:
   python -m venv venv
   .\venv\Scripts\activate

3. Instale as dependências:
   pip install -r requirements.txt

4. Crie o arquivo .env e adicione as credenciais.

5. Execute a API:
   python app.py

A API rodará em http://127.0.0.1:10000/ e a página de testes em /test.
```

---

📄 **Exemplo de .env**

```
DOMAIN_A_API_TOKEN=seu_token_secreto_aqui_123
DOMAIN_B_API_TOKEN=seu_token_secreto_aqui_456

# --- Banco de Dados (Ex: Supabase) ---
# Conexão de LEITURA (para a API)
DOMAIN_A_DATABASE_URL_READER="postgresql://user:pass@host:port/db"
DOMAIN_B_DATABASE_URL_READER="postgresql://user:pass@host:port/db"

# Conexão de ESCRITA (para o ETL)
DOMAIN_A_DATABASE_URL_WRITER="postgresql://user:pass@host:port/db"
DOMAIN_B_DATABASE_URL_WRITER="postgresql://user:pass@host:port/db"

# --- Google Service Account (JSON em uma linha) ---
DOMAIN_A_GOOGLE_CREDENTIALS_JSON='{"type": "service_account", "project_id": ...}'
DOMAIN_B_GOOGLE_CREDENTIALS_JSON='{"type": "service_account", "project_id": ...}'

# --- Mapeamento de Planilhas (JSON em uma linha) ---
DOMAIN_A_PLANILHAS_JSON='[{"id":"id_google_sheet_1", "prefix":"nome_tabela_destino_1"}]'
DOMAIN_A_ARQUIVOS_EXCEL_JSON='[{"id":"id_google_drive_excel_1", "prefix":"nome_tabela_excel_1"}]'
DOMAIN_B_PLANILHAS_JSON='[{"id":"id_google_sheet_2", "prefix":"nome_tabela_destino_2"}]'
DOMAIN_B_ARQUIVOS_EXCEL_JSON='[]'
```

---

☁️ **Deploy & Automação (CI/CD)**

🔹 **Deploy da API (Render)**
- Serviço: Web Service
- Runtime: Python
- Build: pip install -r requirements.txt
- Start: gunicorn app:app
- Variáveis: mesmas do .env

🔹 **Automação ETL (GitHub Actions)**
- Workflow: .github/workflows/sincroniza.yml
- Executa: sincroniza_github.py diariamente
- Credenciais de escrita e Google são configuradas como Secrets

---

👨‍💻 **Autor**

Feito por **João Vitor**
