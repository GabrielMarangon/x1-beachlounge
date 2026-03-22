# X1_BTC

Aplicação Flask para gestão de ranking, desafios, agenda de quadras, resultados e secretaria do clube.

## O problema que causava perda de dados

O projeto usava o diretório `dados/` do repositório como bootstrap e, em alguns cenários, também como armazenamento operacional. Em ambiente Render isso é perigoso porque:

- deploy e restart podem trocar o container
- filesystem do container é efêmero
- sem um diretório persistente explícito, o app podia voltar para arquivos seed do repositório

O efeito prático era o sistema "renascer" após deploy, restart ou nova publicação.

## Como a persistência funciona agora

O app separa dois conceitos:

- `dados/` dentro do projeto: bootstrap somente leitura para primeira inicialização
- `DATA_DIR`: diretório operacional persistente onde ficam SQLite e JSONs espelho

Arquivos operacionais persistidos em `DATA_DIR`:

- `x1_btc.db`
- `atletas.json`
- `quadras.json`
- `horarios.json`
- `partidas.json`
- `access_logs.json`
- backups `*.last_nonempty.json`

Regras de segurança implementadas:

- em produção/Render, se `DATA_DIR` não estiver definido, o app falha no boot com mensagem clara
- se `DATA_DIR` apontar para um diretório inexistente ou sem permissão, o app falha no boot
- o bootstrap do repositório só é aplicado quando o diretório persistente ainda está vazio
- se já existir base persistida, o bootstrap não sobrescreve produção
- na primeira migração, dados legados encontrados fora do diretório persistente são copiados para `DATA_DIR` sem apagar o que já existir lá

## Rodar localmente

Sem `DATA_DIR`, o ambiente local usa `./.runtime_data` automaticamente:

```powershell
python app.py
```

Acesse:

- `http://127.0.0.1:5004`

## Health checks

O endpoint existente continua igual:

- `GET /health`

Novo endpoint de diagnóstico de storage:

- `GET /health/storage`

Ele informa:

- diretório bootstrap
- diretório operacional
- caminho do banco
- origem da configuração
- se o runtime existe e está gravável
- lista de arquivos presentes no runtime

## Deploy no Render com Persistent Disk

### 1. Criar ou revisar o Web Service

No Render Dashboard:

1. Abra o serviço `x1-btc`
2. Confirme que o plano é `Starter`

### 2. Criar e anexar o Persistent Disk

No Render Dashboard:

1. Entre em `Disks`
2. Crie um disco persistente
3. Anexe esse disco ao serviço `x1-btc`
4. Defina o `Mount Path` como:

```text
/var/data
```

### 3. Configurar as variáveis de ambiente

No Render Dashboard, em `Environment`, configure:

```text
DATA_DIR=/var/data
X1_BTC_REQUIRE_DATA_DIR=1
```

O `render.yaml` já foi preparado com esses valores, mas o ponto crítico é que o `Mount Path` do disco e o `DATA_DIR` sejam exatamente o mesmo caminho.

### 4. Validar no primeiro boot

Após o deploy:

1. Abra os logs do serviço
2. Confirme mensagens como:
   - `Bootstrap de dados configurado em: ...`
   - `Diretorio operacional configurado em: /var/data`
   - `Banco operacional configurado em: /var/data/x1_btc.db`
3. Acesse:

```text
https://SEU-APP.onrender.com/health/storage
```

Você deve ver:

- `runtime_dir` apontando para `/var/data`
- `runtime_exists: true`
- `runtime_writable: true`

## Como validar que a persistência ficou correta

Faça este teste simples:

1. Crie ou altere um atleta, desafio, partida ou resultado no app
2. Confira que a informação apareceu normalmente
3. Execute um restart no serviço pelo Render
4. Abra novamente o app e confirme que o dado continua lá
5. Faça um novo deploy
6. Valide novamente que o mesmo dado permanece

Se o deploy estiver correto, o app deve continuar a partir da base gravada em `/var/data`.

## Testes locais

Rodar validações principais:

```powershell
python -m py_compile app.py datastore.py storage_config.py
python -m unittest discover -s tests -v
```

## Estrutura principal

- `app.py`
- `datastore.py`
- `storage_config.py`
- `regras_ranking.py`
- `agenda.py`
- `ranking_logic.py`
- `utils.py`
- `dados/*.json` (bootstrap)
- `templates/*`
- `static/*`
