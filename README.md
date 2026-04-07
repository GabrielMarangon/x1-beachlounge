# X1 Beach Lounge

Projeto independente criado a partir do `x1_btc`, mantendo a base funcional de ranking, desafios, agenda de quadras, resultados e secretaria, mas com identidade propria e banco separado.

## Diferenca em relacao ao x1_btc

- roda em pasta propria: `apps/x1_beachlounge`
- usa banco proprio: `x1_beachlounge.db`
- usa variavel de seguranca propria: `X1_BEACHLOUNGE_REQUIRE_DATA_DIR`
- nao compartilha runtime, dados ou deploy com o projeto original

O projeto original em `templates/x1_btc` permanece intocado.

## Como rodar localmente

```powershell
cd "C:\meu_chatbot_flask - Copia\apps\x1_beachlounge"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Acesso local:

- `http://127.0.0.1:5005`

Scripts auxiliares:

- `rodar_x1_beachlounge.bat`
- `start_x1_beachlounge.ps1`
- `parar_x1_beachlounge.bat`

## Persistencia de dados

Sem `DATA_DIR`, o ambiente local usa `./.runtime_data` automaticamente.

Arquivos operacionais esperados:

- `x1_beachlounge.db`
- `atletas.json`
- `quadras.json`
- `horarios.json`
- `partidas.json`
- `access_logs.json`
- backups `*.last_nonempty.json`

## Deploy no Render

### 1. Criar o servico

- nome sugerido: `x1-beachlounge`
- ambiente: `Python`

### 2. Configurar Persistent Disk

Monte um disco persistente em:

```text
/var/data
```

### 3. Variaveis de ambiente

Configure:

```text
DATA_DIR=/var/data
X1_BEACHLOUNGE_REQUIRE_DATA_DIR=1
PYTHON_VERSION=3.11.9
```

### 4. Build e start

- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app`

### 5. Validacao apos o deploy

Use:

- `GET /health`
- `GET /health/storage`

O esperado e ver o banco operacional apontando para:

```text
/var/data/x1_beachlounge.db
```

## Observacao

Esta duplicacao foi feita para criar um sistema totalmente independente do `x1_btc`, preservando o projeto original ja em producao.
