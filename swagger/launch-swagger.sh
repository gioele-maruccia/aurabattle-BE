#!/bin/bash

#####################################################################
#         SWAGGER UI + MULTI-API AUTH PROXY LAUNCHER               #
#         Supports: dev and prod environments                       #
#####################################################################

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Parse environment argument
ENV="${1:-dev}"

# Handle stop command
if [[ "$ENV" == "stop" ]]; then
    echo -e "${YELLOW}Stopping all services...${NC}"
    
    # Stop Docker containers
    for container in swagger-ui-docs-dev swagger-ui-docs-prod; do
        if docker ps -a --format '{{.Names}}' | grep -q "^${container}$"; then
            docker stop $container 2>/dev/null && echo "  - Stopped $container" || true
            docker rm $container 2>/dev/null || true
        fi
    done
    
    # Stop proxy processes
    for pidfile in .proxy-dev.pid .proxy-prod.pid; do
        if [ -f "$pidfile" ]; then
            PROXY_PID=$(cat "$pidfile")
            if kill -0 $PROXY_PID 2>/dev/null; then
                kill $PROXY_PID 2>/dev/null && echo "  - Stopped proxy (PID: $PROXY_PID)" || true
            fi
            rm -f "$pidfile"
        fi
    done
    
    # Kill orphaned processes
    pkill -f "node.*auth-proxy.js" 2>/dev/null && echo "  - Killed orphaned processes" || true
    
    rm -f proxy-dev.log proxy-prod.log
    echo -e "${GREEN}All services stopped${NC}"
    exit 0
fi

# Validate environment
if [[ "$ENV" != "dev" && "$ENV" != "prod" ]]; then
    echo -e "${RED}Error: Invalid environment '$ENV'${NC}"
    echo ""
    echo "Usage: $0 [dev|prod|stop]"
    echo ""
    echo "Commands:"
    echo "  $0 dev   # Start with dev environment"
    echo "  $0 prod  # Start with prod environment"
    echo "  $0 stop  # Stop all services"
    echo "  $0       # Start with dev (default)"
    exit 1
fi

# Configuration - use same ports, but switch environments
SWAGGER_FILE="./swagger-bundled.yml"
SWAGGER_PORT=8080
PROXY_PORT=8081
SWAGGER_CONTAINER="swagger-ui-docs-${ENV}"
PROXY_PID_FILE=".proxy-${ENV}.pid"
PROXY_LOG="proxy-${ENV}.log"

# Determine the OTHER environment
OTHER_ENV="prod"
if [ "$ENV" = "prod" ]; then
    OTHER_ENV="dev"
fi

# Environment-specific colors
if [ "$ENV" = "prod" ]; then
    ENV_COLOR="${RED}"
    ENV_EMOJI="🔴"
else
    ENV_COLOR="${GREEN}"
    ENV_EMOJI="🟢"
fi

print_header() {
    echo -e "${CYAN}"
    echo "============================================================"
    echo "     SWAGGER UI + COGNITO AUTH - LAUNCHER"
    echo "     Environment: ${ENV_EMOJI} ${ENV^^}"
    echo "============================================================"
    echo -e "${NC}"
}

check_docker() {
    echo -e "${BLUE}[1/5]${NC} Checking Docker..."
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}❌ Docker not found${NC}"
        exit 1
    fi
    
    if ! docker ps &> /dev/null; then
        echo -e "${RED}❌ Docker daemon not running${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ Docker ready${NC}"
}

check_node() {
    echo -e "${BLUE}[2/5]${NC} Checking Node.js..."
    if ! command -v node &> /dev/null; then
        echo -e "${RED}❌ Node.js not found${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ Node.js ready ($(node --version))${NC}"
}

check_aws_cli() {
    echo -e "${BLUE}[3/5]${NC} Checking AWS CLI..."
    if ! command -v aws &> /dev/null; then
        echo -e "${RED}❌ AWS CLI not found${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ AWS CLI ready${NC}"
}

check_swagger_file() {
    echo -e "${BLUE}[4/5]${NC} Checking swagger-bundled.yml..."
    
    if [ ! -f "$SWAGGER_FILE" ]; then
        echo -e "${RED}❌ swagger-bundled.yml not found at: $SWAGGER_FILE${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✓ swagger-bundled.yml found${NC}"
}

check_auth_proxy() {
    echo -e "${BLUE}[5/5]${NC} Checking auth-proxy.js..."
    if [ ! -f "auth-proxy.js" ]; then
        echo -e "${RED}❌ auth-proxy.js not found${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ auth-proxy.js found${NC}"
}

cleanup_env() {
    echo ""
    echo -e "${YELLOW}Cleaning up services...${NC}"
    
    # Stop ALL Docker containers (both envs use same ports)
    for container in swagger-ui-docs-dev swagger-ui-docs-prod swagger-ui-docs; do
        if docker ps -a --format '{{.Names}}' | grep -q "^${container}$"; then
            docker stop $container 2>/dev/null || true
            docker rm $container 2>/dev/null || true
            echo "  - Stopped $container"
        fi
    done
    
    # Stop ALL proxy processes (both envs)
    for pidfile in .proxy-dev.pid .proxy-prod.pid .proxy.pid; do
        if [ -f "$pidfile" ]; then
            PROXY_PID=$(cat "$pidfile")
            if kill -0 $PROXY_PID 2>/dev/null; then
                kill $PROXY_PID 2>/dev/null || true
                echo "  - Stopped proxy (PID: $PROXY_PID)"
            fi
            rm -f "$pidfile"
        fi
    done
    
    # Kill any orphaned proxy
    pkill -f "node.*auth-proxy.js" 2>/dev/null && echo "  - Killed orphaned processes" || true
    
    rm -f proxy-dev.log proxy-prod.log proxy.log
    sleep 1
    echo -e "${GREEN}✓ Cleanup complete${NC}"
}

start_proxy() {
    echo ""
    echo -e "${ENV_COLOR}============================================================${NC}"
    echo -e "${ENV_COLOR}     STARTING AUTH PROXY - ${ENV^^} ENVIRONMENT${NC}"
    echo -e "${ENV_COLOR}============================================================${NC}"
    echo ""
    
    # CRITICAL: Pass ENV as environment variable
    ENV=$ENV node auth-proxy.js > "$PROXY_LOG" 2>&1 &
    PROXY_PID=$!
    echo $PROXY_PID > "$PROXY_PID_FILE"
    
    echo -n "Waiting for proxy"
    ATTEMPTS=0
    while [ $ATTEMPTS -lt 10 ]; do
        if ! kill -0 $PROXY_PID 2>/dev/null; then
            echo ""
            echo -e "${RED}❌ Auth proxy failed${NC}"
            echo ""
            tail -30 "$PROXY_LOG"
            exit 1
        fi
        
        if curl -s http://localhost:$PROXY_PORT > /dev/null 2>&1; then
            break
        fi
        
        echo -n "."
        sleep 0.5
        ATTEMPTS=$((ATTEMPTS + 1))
    done
    echo ""
    
    echo -e "${GREEN}✓ Auth proxy running (PID: $PROXY_PID)${NC}"
}

start_swagger() {
    echo ""
    echo -e "${BLUE}============================================================${NC}"
    echo -e "${BLUE}     STARTING SWAGGER UI${NC}"
    echo -e "${BLUE}============================================================${NC}"
    echo ""
    
    SWAGGER_DIR=$(cd "$(dirname "$SWAGGER_FILE")" && pwd)
    SWAGGER_FILENAME=$(basename "$SWAGGER_FILE")
    
    docker run -d \
        --name $SWAGGER_CONTAINER \
        -p $SWAGGER_PORT:8080 \
        -e SWAGGER_JSON="/api/$SWAGGER_FILENAME" \
        -v "$SWAGGER_DIR:/api" \
        swaggerapi/swagger-ui > /dev/null
    
    if [ $? -ne 0 ]; then
        echo -e "${RED}❌ Swagger UI failed${NC}"
        exit 1
    fi
    
    echo -n "Waiting for Swagger UI"
    ATTEMPTS=0
    while [ $ATTEMPTS -lt 20 ]; do
        if curl -s http://localhost:$SWAGGER_PORT > /dev/null 2>&1; then
            break
        fi
        echo -n "."
        sleep 1
        ATTEMPTS=$((ATTEMPTS + 1))
    done
    echo ""
    
    echo -e "${GREEN}✓ Swagger UI ready${NC}"
}

print_success() {
    echo ""
    echo -e "${ENV_COLOR}╔════════════════════════════════════════╗${NC}"
    echo -e "${ENV_COLOR}║                                        ║${NC}"
    echo -e "${ENV_COLOR}║     ${ENV_EMOJI}  ${ENV^^} ENVIRONMENT READY  ${ENV_EMOJI}     ║${NC}"
    echo -e "${ENV_COLOR}║                                        ║${NC}"
    echo -e "${ENV_COLOR}╚════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${CYAN}🌐 Access Points:${NC}"
    echo "   Swagger UI:  http://localhost:$SWAGGER_PORT"
    echo "   Auth Proxy:  http://localhost:$PROXY_PORT"
    echo ""
    echo -e "${CYAN}📋 Quick Start:${NC}"
    echo "   1. Browser will open automatically"
    echo "   2. Select server: http://localhost:8081"
    echo "   3. Test login: POST /auth/login/users"
    echo "   4. Copy idToken from response"
    echo "   5. Click 'Authorize' and paste token"
    echo ""
    echo -e "${CYAN}🔧 Management:${NC}"
    echo "   View logs:  tail -f $PROXY_LOG"
    echo "   Stop all:   $0 stop"
    echo ""
    echo -e "${CYAN}📚 Documentation:${NC}"
    echo "   See README.md for full API documentation"
    echo ""
}

open_browser() {
    URL="http://localhost:$SWAGGER_PORT"
    
    if command -v xdg-open &> /dev/null; then
        xdg-open "$URL" &> /dev/null &
    elif command -v open &> /dev/null; then
        open "$URL" &> /dev/null &
    elif command -v start &> /dev/null; then
        start "$URL" &> /dev/null &
    elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
        cmd.exe /c start "$URL" &> /dev/null &
    fi
}

# Main execution
print_header
check_docker
check_node
check_aws_cli
check_swagger_file
check_auth_proxy
cleanup_env
start_proxy
start_swagger
print_success
open_browser

echo -e "${GREEN}✅ Setup complete!${NC}"
echo ""