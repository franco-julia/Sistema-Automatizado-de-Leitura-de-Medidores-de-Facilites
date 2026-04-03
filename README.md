# Meter Reader MVP

MVP para autoleitura de medidores (água, gás, eletricidade) com visão computacional.

## Componentes
- **API (FastAPI)**: upload de imagens/vídeos, listagem e confirmação de leituras.
- **Worker de Inferência (PyTorch/ONNX stub)**: consome mídia de uma fila simples (diretório) e gera leituras.
- **Infra (Docker Compose)**: API + Worker + Postgres (opcional).

## Rodar local (sem Docker)
1. Crie venv e instale dependências da API:
   ```bash
   cd meter_reader/services/api
   python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   uvicorn app:app --reload --port 8000
   ```
2. Em outro terminal, rode o worker:
   ```bash
   cd meter_reader/services/vision_infer
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   python worker.py
   ```

## Rodar com Docker
```bash
cd meter_reader/infra/docker
docker compose up --build
```

## Estrutura
```
meter_reader/
  services/
    api/            # FastAPI
    vision_infer/   # Worker + pipeline de inferência (stub)
  infra/
    docker/         # Dockerfiles + compose
    sql/            # schema.sql
  models/           # modelos (coloque pesos aqui)
  datasets/         # datasets (não versionar em git grande)
  scripts/          # instruções de treino
  docs/             # documentação
```

## Fluxo (MVP simplificado)
- API recebe upload em `/api/uploads` → grava em `storage/uploads/queue` + cria registro em SQLite/Postgres.
- Worker monitora `storage/uploads/queue` → roda `infer_pipeline.py` (stub) → salva leitura em `storage/readings/*.json` e chama endpoint interno da API (ou grava direto no DB).
- Cliente consulta `GET /api/readings?meter_id=...` para ver resultados.