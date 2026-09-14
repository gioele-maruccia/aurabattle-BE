#!/bin/bash

# Utility functions for API testing

# Check if required commands are available
check_dependencies() {
    local missing_deps=()
    
    for cmd in curl jq aws; do
        if ! command -v $cmd &> /dev/null; then
            missing_deps+=($cmd)
        fi
    done
    
    if [[ ${#missing_deps[@]} -gt 0 ]]; then
        echo -e "${RED}Error: Missing required dependencies: ${missing_deps[*]}${NC}"
        echo "Please install:"
        for dep in "${missing_deps[@]}"; do
            case $dep in
                curl)
                    echo "  - curl: sudo apt-get install curl (or brew install curl)"
                    ;;
                jq)
                    echo "  - jq: sudo apt-get install jq (or brew install jq)"
                    ;;
                aws)
                    echo "  - aws-cli: pip install awscli"
                    ;;
            esac
        done
        exit 1
    fi
}

# Validate JSON file
validate_json() {
    local file=$1
    
    if [[ ! -f "$file" ]]; then
        echo -e "${RED}Error: File not found: $file${NC}"
        return 1
    fi
    
    if ! jq empty "$file" 2>/dev/null; then
        echo -e "${RED}Error: Invalid JSON in file: $file${NC}"
        return 1
    fi
    
    return 0
}

# Pretty print JSON
print_json() {
    local json=$1
    echo "$json" | jq '.' 2>/dev/null || echo "$json"
}

# Get API URL from CloudFormation stack
get_api_url_from_stack() {
    local stack_name=$1
    local output_key=$2
    local region=$3
    
    aws cloudformation describe-stacks \
        --stack-name "$stack_name" \
        --region "$region" \
        --query "Stacks[0].Outputs[?OutputKey=='$output_key'].OutputValue" \
        --output text 2>/dev/null
}

# Update environment config with actual API URLs
update_env_config() {
    local env=$1
    local config_file="$CONFIG_DIR/env.$env.json"
    
    echo -e "${BLUE}Updating environment config with actual API URLs...${NC}"
    
    local region=$(jq -r '.region' "$config_file")
    
    # Update job-listings API URL
    local jl_stack=$(jq -r '.apis.jobListings.stackName' "$config_file")
    local jl_url=$(get_api_url_from_stack "$jl_stack" "JobListingsApiUrl" "$region")
    
    if [[ -n "$jl_url" ]]; then
        local temp=$(mktemp)
        jq ".apis.jobListings.baseUrl = \"$jl_url\"" "$config_file" > "$temp" && mv "$temp" "$config_file"
        echo -e "${GREEN}  ✓ Updated JobListings API URL${NC}"
    fi
    
    # Add more APIs as needed...
    
    echo -e "${GREEN}Environment config updated${NC}"
}

# Format duration in human readable format
format_duration() {
    local seconds=$1
    
    if [[ $seconds -lt 1 ]]; then
        echo "${seconds}ms"
    elif [[ $seconds -lt 60 ]]; then
        printf "%.2fs" "$seconds"
    else
        local minutes=$((seconds / 60))
        local remaining=$((seconds % 60))
        echo "${minutes}m ${remaining}s"
    fi
}

# Log with timestamp
log_info() {
    echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[$(date '+%H:%M:%S')]${NC} $1"
}

log_error() {
    echo -e "${RED}[$(date '+%H:%M:%S')]${NC} $1"
}

# Extract value from JSON using jq path
json_extract() {
    local json_file=$1
    local json_path=$2
    
    jq -r "$json_path // empty" "$json_file"
}

# Compare two JSON values
json_compare() {
    local actual=$1
    local expected=$2
    
    if [[ "$actual" == "$expected" ]]; then
        return 0
    else
        return 1
    fi
}

# URL encode string
urlencode() {
    local string=$1
    local encoded=""
    local pos char
    
    for ((pos=0; pos<${#string}; pos++)); do
        char=${string:$pos:1}
        case "$char" in
            [-_.~a-zA-Z0-9])
                encoded+="$char"
                ;;
            *)
                encoded+=$(printf '%%%02X' "'$char")
                ;;
        esac
    done
    
    echo "$encoded"
}

# Generate UUID v4
generate_uuid() {
    if command -v uuidgen &> /dev/null; then
        uuidgen | tr '[:upper:]' '[:lower:]'
    else
        cat /proc/sys/kernel/random/uuid
    fi
}

# Wait for API to be ready
wait_for_api() {
    local url=$1
    local max_attempts=${2:-30}
    local attempt=1
    
    echo -e "${BLUE}Waiting for API to be ready...${NC}"
    
    while [[ $attempt -le $max_attempts ]]; do
        if curl -s -f -o /dev/null "$url"; then
            echo -e "${GREEN}✓ API is ready${NC}"
            return 0
        fi
        
        echo -e "${YELLOW}  Attempt $attempt/$max_attempts...${NC}"
        sleep 2
        ((attempt++))
    done
    
    echo -e "${RED}✗ API failed to become ready${NC}"
    return 1
}

# Check dependencies on script load
check_dependencies