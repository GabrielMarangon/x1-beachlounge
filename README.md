# X1_BTC

Aplicação Flask para gestão de ranking, desafios, agenda de quadras e resultados do clube.

## Rodar local

```powershell
python app.py
```

Acesse: `http://127.0.0.1:5004`

## Deploy no Render (Blueprint)

- Arquivo: `render.yaml`
- Build: `pip install -r requirements.txt`
- Start: `gunicorn app:app`

## Estrutura principal

- `app.py`
- `regras_ranking.py`
- `agenda.py`
- `ranking_logic.py`
- `utils.py`
- `dados/*.json`
- `templates/*`
- `static/*`
