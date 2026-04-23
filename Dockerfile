FROM python:3.11-slim

WORKDIR /app

# Copiar todo o projeto
COPY . .

# Instalar dependências
RUN pip install --no-cache-dir -r backend/requirements.txt

# Definir PYTHONPATH para reconhecer imports do backend
ENV PYTHONPATH=/app/backend

# Rodar worker
CMD ["python", "backend/worker.py"]
