#!/bin/bash

# Authentication Helper for Beezey API Tests
# Manages Cognito tokens

# If running standalone, set up paths
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
    CONFIG_DIR="$PROJECT_ROOT/config"
fi

# Get Cognito token for user type
get_cognito_token() {
    local user_type=$1
    local env=$2
    
    local auth_file="$CONFIG_DIR/auth.json"
    
    # Check if auth file exists
    if [[ ! -f "$auth_file" ]]; then
        echo -e "${YELLOW}Warning: auth.json not found. Creating template...${NC}" >&2
        create_auth_template
        return 1
    fi
    
    # Try to get existing valid token
    local token=$(jq -r ".${env}.${user_type}.token // empty" "$auth_file")
    local expiry=$(jq -r ".${env}.${user_type}.expiresAt // empty" "$auth_file")
    
    # Check if token exists and is not expired
    if [[ -n "$token" ]] && [[ -n "$expiry" ]]; then
        local now=$(date +%s)
        if [[ $now -lt $expiry ]]; then
            echo "$token"
            return 0
        fi
    fi
    
    # Token expired or doesn't exist, try to refresh
    if [[ "$VERBOSE" == true ]]; then
        echo -e "${YELLOW}  → Token expired or missing, attempting refresh...${NC}" >&2
    fi
    
    # Try to refresh token
    local refresh_token=$(jq -r ".${env}.${user_type}.refreshToken // empty" "$auth_file")
    
    if [[ -n "$refresh_token" ]]; then
        if refresh_cognito_token "$user_type" "$env" "$refresh_token"; then
            # Get the new token
            token=$(jq -r ".${env}.${user_type}.token // empty" "$auth_file")
            echo "$token"
            return 0
        fi
    fi
    
    # Could not refresh, need manual login
    echo -e "${YELLOW}  → Token refresh failed. Please run: ./scripts/auth-helper.sh login --type $user_type --env $env${NC}" >&2
    return 1
}

# Refresh Cognito token using refresh token
refresh_cognito_token() {
    local user_type=$1
    local env=$2
    local refresh_token=$3
    
    # Get config file path
    local env_config="$CONFIG_DIR/env.$env.json"
    
    if [[ ! -f "$env_config" ]]; then
        echo -e "${RED}Error: Environment config not found: $env_config${NC}" >&2
        return 1
    fi
    
    # Determine which Cognito pool to use based on user type
    local cognito_key
    if [[ "$user_type" == "backoffice" ]]; then
        cognito_key="backoffice"
    else
        cognito_key="users"
    fi
    
    local client_id=$(jq -r ".cognito.${cognito_key}.clientId // empty" "$env_config")
    local region=$(jq -r ".cognito.${cognito_key}.region // empty" "$env_config")
    
    if [[ -z "$client_id" ]] || [[ -z "$region" ]]; then
        echo -e "${RED}Error: Missing Cognito configuration for ${cognito_key}${NC}" >&2
        echo -e "${RED}  clientId: ${client_id}${NC}" >&2
        echo -e "${RED}  region: ${region}${NC}" >&2
        return 1
    fi
    
    # Call Cognito to refresh token
    local response=$(aws cognito-idp initiate-auth \
        --region "$region" \
        --auth-flow REFRESH_TOKEN_AUTH \
        --client-id "$client_id" \
        --auth-parameters REFRESH_TOKEN="$refresh_token" \
        2>/dev/null)
    
    if [[ $? -ne 0 ]]; then
        return 1
    fi
    
    # Extract new token
    local new_token=$(echo "$response" | jq -r '.AuthenticationResult.IdToken // empty')
    local expires_in=$(echo "$response" | jq -r '.AuthenticationResult.ExpiresIn // 3600')
    
    if [[ -z "$new_token" ]]; then
        return 1
    fi
    
    # Calculate expiry timestamp
    local expiry=$(($(date +%s) + expires_in))
    
    # Update auth.json
    local auth_file="$CONFIG_DIR/auth.json"
    local temp_file=$(mktemp)
    
    jq ".${env}.${user_type}.token = \"$new_token\" | .${env}.${user_type}.expiresAt = $expiry" \
        "$auth_file" > "$temp_file" && mv "$temp_file" "$auth_file"
    
    if [[ "$VERBOSE" == true ]]; then
        echo -e "${GREEN}  ✓ Token refreshed successfully${NC}" >&2
    fi
    
    return 0
}

# Login and get new token
login_cognito() {
    local user_type=$1
    local env=$2
    
    echo "Authenticating with Cognito..." >&2
    
    # Get config file path
    local env_config="$CONFIG_DIR/env.$env.json"
    
    if [[ ! -f "$env_config" ]]; then
        echo -e "${RED}Error: Environment config not found: $env_config${NC}" >&2
        echo -e "${YELLOW}Current directory: $(pwd)${NC}" >&2
        echo -e "${YELLOW}Looking for: $env_config${NC}" >&2
        return 1
    fi
    
    # Get username from config
    local username=$(jq -r ".testUsers.${user_type}.username // empty" "$env_config")
    
    if [[ -z "$username" ]] || [[ "$username" == "null" ]]; then
        echo -e "${RED}Error: Username not configured for user type: ${user_type}${NC}" >&2
        echo -e "${YELLOW}Please update config/env.${env}.json with testUsers.${user_type}.username${NC}" >&2
        return 1
    fi
    
    # Determine which Cognito pool to use
    local cognito_key
    if [[ "$user_type" == "backoffice" ]]; then
        cognito_key="backoffice"
    else
        cognito_key="users"
    fi
    
    local client_id=$(jq -r ".cognito.${cognito_key}.clientId // empty" "$env_config")
    local region=$(jq -r ".cognito.${cognito_key}.region // empty" "$env_config")
    
    if [[ -z "$client_id" ]] || [[ "$client_id" == "null" ]]; then
        echo -e "${RED}Error: Cognito clientId not configured for ${cognito_key}${NC}" >&2
        echo -e "${YELLOW}Please update config/env.${env}.json with cognito.${cognito_key}.clientId${NC}" >&2
        return 1
    fi
    
    if [[ -z "$region" ]] || [[ "$region" == "null" ]]; then
        echo -e "${RED}Error: Cognito region not configured for ${cognito_key}${NC}" >&2
        echo -e "${YELLOW}Please update config/env.${env}.json with cognito.${cognito_key}.region${NC}" >&2
        return 1
    fi
    
    # Debug output
    echo "Using configuration:" >&2
    echo "  User type: $user_type" >&2
    echo "  Username: $username" >&2
    echo "  Cognito pool: $cognito_key" >&2
    echo "  Region: $region" >&2
    echo "  Client ID: ${client_id:0:10}..." >&2
    echo "" >&2
    
    # Prompt for password
    echo -n "Enter password for $username: " >&2
    read -s password
    echo "" >&2
    
    if [[ -z "$password" ]]; then
        echo -e "${RED}Error: Password cannot be empty${NC}" >&2
        return 1
    fi
    
    # Authenticate with Cognito
    echo "Calling AWS Cognito..." >&2
    local response=$(aws cognito-idp initiate-auth \
        --region "$region" \
        --auth-flow USER_PASSWORD_AUTH \
        --client-id "$client_id" \
        --auth-parameters USERNAME="$username",PASSWORD="$password" \
        2>&1)
    
    local exit_code=$?
    
    if [[ $exit_code -ne 0 ]]; then
        echo -e "${RED}Error: Authentication failed${NC}" >&2
        echo -e "${RED}AWS CLI exit code: $exit_code${NC}" >&2
        echo -e "${RED}Response:${NC}" >&2
        echo "$response" >&2
        return 1
    fi
    
    # Check if response is valid JSON
    if ! echo "$response" | jq empty 2>/dev/null; then
        echo -e "${RED}Error: Invalid JSON response from AWS${NC}" >&2
        echo -e "${RED}Response:${NC}" >&2
        echo "$response" >&2
        return 1
    fi
    
    # Extract tokens
    local id_token=$(echo "$response" | jq -r '.AuthenticationResult.IdToken // empty')
    local refresh_token=$(echo "$response" | jq -r '.AuthenticationResult.RefreshToken // empty')
    local expires_in=$(echo "$response" | jq -r '.AuthenticationResult.ExpiresIn // 3600')
    
    if [[ -z "$id_token" ]] || [[ "$id_token" == "null" ]]; then
        echo -e "${RED}Error: Failed to get ID token from response${NC}" >&2
        echo -e "${RED}Response structure:${NC}" >&2
        echo "$response" | jq '.' >&2
        return 1
    fi
    
    # Calculate expiry
    local expiry=$(($(date +%s) + expires_in))
    
    # Ensure auth.json exists
    local auth_file="$CONFIG_DIR/auth.json"
    if [[ ! -f "$auth_file" ]]; then
        echo "{}" > "$auth_file"
    fi
    
    # Create temporary file for jq operation
    local temp_file=$(mktemp)
    
    # Ensure the environment object exists first
    jq ". + {\"${env}\": (.${env} // {})}" "$auth_file" > "$temp_file" && mv "$temp_file" "$auth_file"
    
    # Now update the user type
    jq ".${env}.${user_type} = {\"token\": \"$id_token\", \"refreshToken\": \"$refresh_token\", \"expiresAt\": $expiry}" \
        "$auth_file" > "$temp_file" && mv "$temp_file" "$auth_file"
    
    if [[ $? -eq 0 ]]; then
        echo -e "${GREEN}✓ Login successful for $user_type in $env${NC}" >&2
        echo -e "${GREEN}  Token will expire in $((expires_in / 60)) minutes${NC}" >&2
        echo -e "${GREEN}  Token saved to: $auth_file${NC}" >&2
        echo "" >&2
        echo -e "${CYAN}Token preview (first 50 chars):${NC}" >&2
        echo "${id_token:0:50}..." >&2
    else
        echo -e "${RED}✗ Failed to save token to $auth_file${NC}" >&2
        return 1
    fi
    
    return 0
}

# Create auth.json template
create_auth_template() {
    local auth_file="$CONFIG_DIR/auth.json"
    
    cat > "$auth_file" <<EOF
{
  "dev": {
    "company": {
      "token": "",
      "refreshToken": "",
      "expiresAt": 0
    },
    "company2": {
      "token": "",
      "refreshToken": "",
      "expiresAt": 0
    },
    "worker": {
      "token": "",
      "refreshToken": "",
      "expiresAt": 0
    },
    "backoffice": {
      "token": "",
      "refreshToken": "",
      "expiresAt": 0
    }
  },
  "prod": {
    "company": {
      "token": "",
      "refreshToken": "",
      "expiresAt": 0
    },
    "company2": {
      "token": "",
      "refreshToken": "",
      "expiresAt": 0
    },
    "worker": {
      "token": "",
      "refreshToken": "",
      "expiresAt": 0
    },
    "backoffice": {
      "token": "",
      "refreshToken": "",
      "expiresAt": 0
    }
  }
}
EOF
    
    echo -e "${GREEN}Created auth.json template at: $auth_file${NC}"
    echo -e "${YELLOW}Run: ./scripts/auth-helper.sh login --type company --env dev${NC}"
}

# Main function for standalone usage
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    # Colors for standalone mode
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    CYAN='\033[0;36m'
    NC='\033[0m'
    
    # Parse arguments
    COMMAND=""
    USER_TYPE=""
    ENV="dev"
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            login)
                COMMAND="login"
                shift
                ;;
            --type)
                USER_TYPE="$2"
                shift 2
                ;;
            --env)
                ENV="$2"
                shift 2
                ;;
            *)
                echo "Unknown option: $1"
                echo "Usage: $0 login --type {company|company2|worker|backoffice} --env {dev|prod}"
                exit 1
                ;;
        esac
    done
    
    if [[ "$COMMAND" == "login" ]]; then
        if [[ -z "$USER_TYPE" ]]; then
            echo -e "${RED}Error: --type is required${NC}"
            echo "Usage: $0 login --type {company|company2|worker|backoffice} --env {dev|prod}"
            exit 1
        fi
        
        # Validate user type
        case "$USER_TYPE" in
            company|company2|worker|backoffice)
                # Valid
                ;;
            *)
                echo -e "${RED}Error: Invalid user type: $USER_TYPE${NC}"
                echo "Valid types: company, company2, worker, backoffice"
                exit 1
                ;;
        esac
        
        # Check if config file exists
        if [[ ! -f "$CONFIG_DIR/env.$ENV.json" ]]; then
            echo -e "${RED}Error: Config file not found: $CONFIG_DIR/env.$ENV.json${NC}"
            echo -e "${YELLOW}Current directory: $(pwd)${NC}"
            echo -e "${YELLOW}Script directory: $SCRIPT_DIR${NC}"
            echo -e "${YELLOW}Config directory: $CONFIG_DIR${NC}"
            echo ""
            echo -e "${YELLOW}Make sure you're running from the tests/ directory:${NC}"
            echo "  cd tests"
            echo "  ./scripts/auth-helper.sh login --type $USER_TYPE --env $ENV"
            exit 1
        fi
        
        login_cognito "$USER_TYPE" "$ENV"
        exit $?
    else
        echo "Usage: $0 login --type {company|company2|worker|backoffice} --env {dev|prod}"
        exit 1
    fi
fi