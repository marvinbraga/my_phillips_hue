#!/bin/bash

# Script para inicializar o servidor Marvin Hue facilmente

# Cores para output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 Iniciando Marvin Hue Server...${NC}"

# Verificar se o arquivo .env existe
if [ ! -f .env ]; then
    echo -e "${YELLOW}⚠️  Arquivo .env não encontrado!${NC}"
    echo -e "${YELLOW}   Copie .env.example para .env e configure o bridge_ip${NC}"
    exit 1
fi

# Verificar se uv está instalado
if ! command -v uv &> /dev/null; then
    echo -e "${RED}❌ uv não está instalado!${NC}"
    echo -e "${RED}   Instale com: curl -LsSf https://astral.sh/uv/install.sh | sh${NC}"
    exit 1
fi

# Porta padrão
PORT=${1:-5081}

echo -e "${GREEN}📡 Servidor será iniciado na porta ${PORT}${NC}"
echo -e "${GREEN}🌐 Acesse: http://localhost:${PORT}${NC}"
echo -e "${YELLOW}   Pressione Ctrl+C para parar o servidor${NC}"
echo ""

# Iniciar o servidor com auto-reload
uv run uvicorn app:app --reload --port ${PORT}
