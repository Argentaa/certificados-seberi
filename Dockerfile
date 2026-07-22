FROM python:3.12-slim

# Instala dependências do sistema (fontes para Pillow e bibliotecas para SQLite)
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copia e instala dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código do app
COPY . .

# Cria diretórios necessários
RUN mkdir -p instance certificates

# Expõe a porta do gunicorn
EXPOSE 5000

# Usa gunicorn em produção
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000", "--workers", "4", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-"]
