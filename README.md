# Certificados Seberi

Sistema de emissão de certificados da Prefeitura Municipal de Seberi-RS.

## Deploy com Docker Compose

### 1. Pré-requisitos na VPS

```bash
# Instalar Docker e Docker Compose
curl -fsSL https://get.docker.com | bash
```

### 2. Setup

```bash
git clone <url-do-repo> /opt/certificados-seberi
cd /opt/certificados-seberi

# Configurar variáveis de ambiente
cp .env.example .env
nano .env
# Altere SECRET_KEY e ADMIN_PASSWORD obrigatoriamente!
```

### 3. SSL (Let's Encrypt)

```bash
mkdir ssl
# Opção 1: Certificado auto-assinado (teste)
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout ssl/key.pem -out ssl/cert.pem \
  -subj "/CN=seudominio.com.br"

# Opção 2: Let's Encrypt (recomendado)
# Instale certbot e gere os certificados para seu domínio
```

### 4. Subir

```bash
docker compose up -d --build
```

### 5. Verificar

```bash
docker compose logs -f
```

O app estará em `https://seudominio.com.br`.

### Estrutura de volumes

| Caminho no container | Uso |
|---|---|
| `/app/instance` | Banco SQLite |
| `/app/certificates` | Certificados gerados |
| `/app/certificate_template.png` | Template opcional |

### Atualizar

```bash
cd /opt/certificados-seberi
git pull
docker compose up -d --build --pull
```
