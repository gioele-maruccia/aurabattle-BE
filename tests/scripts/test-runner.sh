#!/bin/bash

# API Test Runner for Beezey Platform
# Usage: ./test-runner.sh --suite job-listings --env dev [options]

# Don't exit on error during initialization
set +e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TESTS_DIR="$PROJECT_ROOT"
CONFIG_DIR="$TESTS_DIR/config"
SUITES_DIR="$TESTS_DIR/test-suites"
RESULTS_DIR="$TESTS_DIR/results"

# Create results directory if it doesn't exist
mkdir -p "$RESULTS_DIR"

# Default values
SUITE=""
ENV="dev"
TEST_ID=""
VERBOSE=false
REPORT=false
AUTH_TYPE=""
DEBUG=false

# Temporary files
TEMP_RESPONSE="/tmp/api_test_response_$$.json"
TEMP_HEADERS="/tmp/api_test_headers_$$.txt"
TEMP_RESULTS="/tmp/api_test_results_$$.txt"

# Test results tracking
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0
SKIPPED_TESTS=0

# Use a temporary file instead of associative array for macOS compatibility
TEST_RESULTS_FILE="/tmp/test_results_$$.txt"
touch "$TEST_RESULTS_FILE"

# Usage function
usage() {
    echo "Usage: $0 --suite SUITE_NAME --env ENVIRONMENT [OPTIONS]"
    echo ""
    echo "Required:"
    echo "  --suite SUITE_NAME    Test suite to run (e.g., job-listings, bookings, companies)"
    echo "  --env ENVIRONMENT     Environment to test (dev, prod)"
    echo ""
    echo "Optional:"
    echo "  --test TEST_ID        Run specific test by ID"
    echo "  --auth AUTH_TYPE      Authentication type (company, worker, none)"
    echo "  --verbose             Enable verbose output"
    echo "  --report              Generate detailed report"
    echo "  --debug               Enable debug mode"
    echo "  --help                Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 --suite job-listings --env dev"
    echo "  $0 --suite job-listings --env dev --test create-listing-valid"
    echo "  $0 --suite job-listings --env dev --verbose --report"
    exit 1
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --suite)
            SUITE="$2"
            shift 2
            ;;
        --env)
            ENV="$2"
            shift 2
            ;;
        --test)
            TEST_ID="$2"
            shift 2
            ;;
        --auth)
            AUTH_TYPE="$2"
            shift 2
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        --debug)
            DEBUG=true
            set -x  # Enable bash debug mode
            shift
            ;;
        --report)
            REPORT=true
            shift
            ;;
        --help)
            usage
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

# Validate required arguments
if [[ -z "$SUITE" ]]; then
    echo -e "${RED}Error: --suite is required${NC}"
    usage
fi

# Debug info
if [[ "$DEBUG" == true ]] || [[ "$VERBOSE" == true ]]; then
    echo -e "${BLUE}Debug Info:${NC}"
    echo -e "  SCRIPT_DIR: $SCRIPT_DIR"
    echo -e "  PROJECT_ROOT: $PROJECT_ROOT"
    echo -e "  CONFIG_DIR: $CONFIG_DIR"
    echo -e "  SUITES_DIR: $SUITES_DIR"
    echo -e "  ENV_CONFIG: $CONFIG_DIR/env.$ENV.json"
    echo -e "  SUITE_CONFIG: $SUITES_DIR/$SUITE/suite.json"
    echo ""
fi

# Load environment configuration
ENV_CONFIG="$CONFIG_DIR/env.$ENV.json"
if [[ ! -f "$ENV_CONFIG" ]]; then
    echo -e "${RED}Error: Environment config not found: $ENV_CONFIG${NC}"
    echo -e "${YELLOW}Current directory: $(pwd)${NC}"
    echo -e "${YELLOW}Script directory: $SCRIPT_DIR${NC}"
    echo -e "${YELLOW}Project root: $PROJECT_ROOT${NC}"
    echo -e "${YELLOW}Config directory: $CONFIG_DIR${NC}"
    exit 1
fi

# Load suite configuration
SUITE_CONFIG="$SUITES_DIR/$SUITE/suite.json"
if [[ ! -f "$SUITE_CONFIG" ]]; then
    echo -e "${RED}Error: Suite config not found: $SUITE_CONFIG${NC}"
    exit 1
fi

# Source utility functions
echo -e "${BLUE}Loading utility scripts...${NC}"

if [[ ! -f "$SCRIPT_DIR/utils.sh" ]]; then
    echo -e "${RED}Error: utils.sh not found at: $SCRIPT_DIR/utils.sh${NC}"
    exit 1
fi

if [[ ! -f "$SCRIPT_DIR/auth-helper.sh" ]]; then
    echo -e "${RED}Error: auth-helper.sh not found at: $SCRIPT_DIR/auth-helper.sh${NC}"
    exit 1
fi

source "$SCRIPT_DIR/utils.sh"
if [[ $? -ne 0 ]]; then
    echo -e "${RED}Error: Failed to source utils.sh${NC}"
    exit 1
fi

source "$SCRIPT_DIR/auth-helper.sh"
if [[ $? -ne 0 ]]; then
    echo -e "${RED}Error: Failed to source auth-helper.sh${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Scripts loaded${NC}"
echo ""

# Print test header
print_header() {
    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║${NC}  Beezey API Test Runner                                     ${BLUE}║${NC}"
    echo -e "${BLUE}╠════════════════════════════════════════════════════════════════╣${NC}"
    echo -e "${BLUE}║${NC}  Suite: ${YELLOW}$SUITE${NC}"
    echo -e "${BLUE}║${NC}  Environment: ${YELLOW}$ENV${NC}"
    echo -e "${BLUE}║${NC}  Time: $(date '+%Y-%m-%d %H:%M:%S')"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

# Get API base URL from config
get_api_base_url() {
    local suite_name=$1
    
    # Convert suite name to camelCase for JSON key
    # job-listings -> jobListings
    # bookings -> bookings
    local key=$(echo "$suite_name" | awk -F'-' '{
        printf "%s", $1;
        for(i=2; i<=NF; i++) {
            printf "%s", toupper(substr($i,1,1)) substr($i,2)
        }
    }')
    
    local url=$(jq -r ".apis.${key}.baseUrl // empty" "$ENV_CONFIG")
    
    if [[ "$VERBOSE" == true ]] || [[ "$DEBUG" == true ]]; then
        echo "  DEBUG: suite_name=$suite_name, key=$key, url=$url" >&2
    fi
    
    echo "$url"
}

# Get authentication token
get_auth_token() {
    local auth_type=$1
    
    if [[ "$auth_type" == "none" ]]; then
        echo ""
        return
    fi
    
    # Try to get token from auth-helper
    get_cognito_token "$auth_type" "$ENV"
}

# Function to store result from previous test (macOS compatible)
store_test_result() {
    local test_id=$1
    local json_path=$2
    local response_file=$3
    
    # Convert JSONPath to jq path ($.field -> .field)
    local jq_path=$(echo "$json_path" | sed 's/^\$//')
    
    # Extract value from response
    local value=$(jq -r "${jq_path} // empty" "$response_file")
    
    if [[ -n "$value" ]] && [[ "$value" != "null" ]]; then
        local key="${test_id}:${json_path}"
        # Store in file instead of associative array
        echo "${key}=${value}" >> "$TEST_RESULTS_FILE"
        
        if [[ "$VERBOSE" == true ]] || [[ "$DEBUG" == true ]]; then
            echo "  DEBUG: Stored result - ${key} = ${value}" >&2
        fi
    fi
}

# Function to get stored result (macOS compatible)
get_test_result() {
    local lookup_key=$1
    
    # Search in the results file
    local result=$(grep "^${lookup_key}=" "$TEST_RESULTS_FILE" 2>/dev/null | tail -1 | cut -d'=' -f2-)
    
    echo "$result"
}

# Function to resolve dynamic parameters
resolve_dynamic_params() {
    local endpoint=$1
    local dynamic_params_json=$2
    
    # If no dynamic params, return original endpoint
    if [[ "$dynamic_params_json" == "null" ]] || [[ -z "$dynamic_params_json" ]]; then
        echo "$endpoint"
        return 0
    fi
    
    local resolved_endpoint="$endpoint"
    
    # Parse each dynamic param
    local params=$(echo "$dynamic_params_json" | jq -r 'to_entries[] | @json')
    
    while IFS= read -r param_json; do
        local param_name=$(echo "$param_json" | jq -r '.key')
        local param_value=$(echo "$param_json" | jq -r '.value')
        
        if [[ "$VERBOSE" == true ]] || [[ "$DEBUG" == true ]]; then
            echo "  DEBUG: Resolving param - ${param_name} = ${param_value}" >&2
        fi
        
        # Check if it's a reference to previous test
        if [[ "$param_value" == fromPreviousTest:* ]]; then
            # Extract test_id and json_path
            # Format: fromPreviousTest:test-id:$.path.to.value
            local remaining="${param_value#fromPreviousTest:}"
            local ref_test_id="${remaining%%:*}"
            local ref_json_path="${remaining#*:}"
            
            # Build lookup key
            local lookup_key="${ref_test_id}:${ref_json_path}"
            
            if [[ "$VERBOSE" == true ]] || [[ "$DEBUG" == true ]]; then
                echo "  DEBUG: Looking up - ${lookup_key}" >&2
            fi
            
            # Get value from stored results
            local actual_value=$(get_test_result "$lookup_key")
            
            if [[ -z "$actual_value" ]]; then
                echo -e "${RED}  ✗ Error: Could not resolve dynamic param ${param_name}${NC}" >&2
                echo -e "${RED}     Referenced test: ${ref_test_id}${NC}" >&2
                echo -e "${RED}     Referenced path: ${ref_json_path}${NC}" >&2
                echo -e "${RED}     Lookup key: ${lookup_key}${NC}" >&2
                echo -e "${RED}     Available results:${NC}" >&2
                if [[ -f "$TEST_RESULTS_FILE" ]]; then
                    cat "$TEST_RESULTS_FILE" >&2
                fi
                return 1
            fi
            
            # Replace in endpoint
            resolved_endpoint="${resolved_endpoint//\{${param_name}\}/${actual_value}}"
            
            if [[ "$VERBOSE" == true ]] || [[ "$DEBUG" == true ]]; then
                echo "  DEBUG: Replaced {${param_name}} with ${actual_value}" >&2
                echo "  DEBUG: Endpoint now: ${resolved_endpoint}" >&2
            fi
        else
            # Static value replacement
            resolved_endpoint="${resolved_endpoint//\{${param_name}\}/${param_value}}"
        fi
    done <<< "$params"
    
    echo "$resolved_endpoint"
    return 0
}

# Execute single test
execute_test() {
    local test_json=$1
    local test_id=$(echo "$test_json" | jq -r '.id')
    local test_name=$(echo "$test_json" | jq -r '.name')
    local method=$(echo "$test_json" | jq -r '.method')
    local endpoint=$(echo "$test_json" | jq -r '.endpoint')
    local auth=$(echo "$test_json" | jq -r '.auth')
    local payload_file=$(echo "$test_json" | jq -r '.payload // empty')
    local expected_status=$(echo "$test_json" | jq -r '.expectedStatus')
    local dynamic_params=$(echo "$test_json" | jq -c '.dynamicParams // null')
    
    ((TOTAL_TESTS++))
    
    echo -e "${BLUE}▶${NC} Running: ${YELLOW}$test_name${NC} (ID: $test_id)"
    
    # Get base URL
    BASE_URL=$(get_api_base_url "$SUITE")
    if [[ -z "$BASE_URL" ]]; then
        echo -e "${RED}  ✗ Failed: Could not get API base URL${NC}"
        ((FAILED_TESTS++))
        return 1
    fi
    
    # Resolve dynamic parameters in endpoint
    if [[ "$dynamic_params" != "null" ]]; then
        if [[ "$VERBOSE" == true ]] || [[ "$DEBUG" == true ]]; then
            echo "  DEBUG: Original endpoint: $endpoint" >&2
            echo "  DEBUG: Dynamic params: $dynamic_params" >&2
        fi
        
        local resolved_endpoint
        resolved_endpoint=$(resolve_dynamic_params "$endpoint" "$dynamic_params")
        
        if [[ $? -ne 0 ]]; then
            echo -e "${RED}  ✗ Failed: Could not resolve dynamic parameters${NC}"
            ((FAILED_TESTS++))
            return 1
        fi
        
        endpoint="$resolved_endpoint"
        
        if [[ "$VERBOSE" == true ]] || [[ "$DEBUG" == true ]]; then
            echo "  DEBUG: Resolved endpoint: $endpoint" >&2
        fi
    fi
    
    # Build full URL
    FULL_URL="${BASE_URL}${endpoint}"
    
    # Get authentication token if needed
    TOKEN=""
    if [[ "$auth" != "none" ]]; then
        TOKEN=$(get_auth_token "$auth")
        if [[ -z "$TOKEN" ]]; then
            echo -e "${YELLOW}  ⊘ Skipped: Could not get authentication token${NC}"
            ((SKIPPED_TESTS++))
            return 0
        fi
    fi
    
    # Build curl command
    CURL_CMD="curl -s -w '\n%{http_code}' -D $TEMP_HEADERS"
    
    # Add authentication header
    if [[ -n "$TOKEN" ]]; then
        CURL_CMD="$CURL_CMD -H 'Authorization: Bearer $TOKEN'"
    fi
    
    # Add content type for POST/PUT/PATCH
    if [[ "$method" == "POST" ]] || [[ "$method" == "PUT" ]] || [[ "$method" == "PATCH" ]]; then
        CURL_CMD="$CURL_CMD -H 'Content-Type: application/json'"
    fi
    
    # Add payload if specified
    if [[ -n "$payload_file" ]]; then
        PAYLOAD_PATH="$SUITES_DIR/$SUITE/$payload_file"
        if [[ ! -f "$PAYLOAD_PATH" ]]; then
            echo -e "${RED}  ✗ Failed: Payload file not found: $PAYLOAD_PATH${NC}"
            ((FAILED_TESTS++))
            return 1
        fi
        CURL_CMD="$CURL_CMD -d @$PAYLOAD_PATH"
    fi
    
    # Add method and URL
    CURL_CMD="$CURL_CMD -X $method '$FULL_URL'"
    
    # Execute request
    if [[ "$VERBOSE" == true ]]; then
        echo -e "${BLUE}  → Request: $method $FULL_URL${NC}"
        if [[ -n "$payload_file" ]]; then
            echo -e "${BLUE}  → Payload: $payload_file${NC}"
        fi
    fi
    
    # Execute and capture response
    RESPONSE=$(eval $CURL_CMD)
    HTTP_CODE=$(echo "$RESPONSE" | tail -n 1)
    BODY=$(echo "$RESPONSE" | sed '$d')
    
    # Save response body to temp file
    echo "$BODY" > "$TEMP_RESPONSE"
    
    if [[ "$VERBOSE" == true ]]; then
        echo -e "${BLUE}  → Status: $HTTP_CODE${NC}"
        echo -e "${BLUE}  → Response:${NC}"
        echo "$BODY" | jq '.' 2>/dev/null || echo "$BODY"
    fi
    
    # Check status code
    if [[ "$HTTP_CODE" -eq "$expected_status" ]]; then
        echo -e "${GREEN}  ✓ Status code: $HTTP_CODE${NC}"
    else
        echo -e "${RED}  ✗ Status code: Expected $expected_status, got $HTTP_CODE${NC}"
        ((FAILED_TESTS++))
        return 1
    fi
    
    # Run assertions
    local assertions=$(echo "$test_json" | jq -c '.assertions[]? // empty')
    local assertion_failed=false
    
    while IFS= read -r assertion; do
        if ! run_assertion "$assertion" "$TEMP_RESPONSE" "$HTTP_CODE"; then
            assertion_failed=true
        fi
    done <<< "$assertions"
    
    # Store test result for potential use in subsequent tests
    if [[ "$HTTP_CODE" -eq "$expected_status" ]] && [[ "$assertion_failed" != true ]]; then
        # Store common paths that might be referenced
        store_test_result "$test_id" "$.listing.listingId" "$TEMP_RESPONSE"
        store_test_result "$test_id" "$.listing.status" "$TEMP_RESPONSE"
        store_test_result "$test_id" "$.listing.companyId" "$TEMP_RESPONSE"
        store_test_result "$test_id" "$.booking.bookingId" "$TEMP_RESPONSE"
        store_test_result "$test_id" "$.booking.listingId" "$TEMP_RESPONSE"
        store_test_result "$test_id" "$.company.companyId" "$TEMP_RESPONSE"
        store_test_result "$test_id" "$.company.userId" "$TEMP_RESPONSE"
    fi
    
    if [[ "$assertion_failed" == true ]]; then
        ((FAILED_TESTS++))
        return 1
    else
        ((PASSED_TESTS++))
        echo -e "${GREEN}  ✓ Test passed${NC}"
        return 0
    fi
}

# Run assertions
run_assertion() {
    local assertion=$1
    local response_file=$2
    local http_code=$3
    
    local type=$(echo "$assertion" | jq -r '.type')
    
    case "$type" in
        status)
            local expected=$(echo "$assertion" | jq -r '.value')
            if [[ "$http_code" -eq "$expected" ]]; then
                return 0
            else
                echo -e "${RED}  ✗ Assertion failed: Status code${NC}"
                return 1
            fi
            ;;
        jsonPath)
            local path=$(echo "$assertion" | jq -r '.path')
            local exists=$(echo "$assertion" | jq -r '.exists // empty')
            local expected_value=$(echo "$assertion" | jq -r '.value // empty')
            local contains=$(echo "$assertion" | jq -r '.contains // empty')
            
            # Convert JSONPath to jq path ($.field -> .field)
            local jq_path=$(echo "$path" | sed 's/^\$//')
            
            local actual=$(jq -r "${jq_path} // empty" "$response_file")
            
            if [[ -n "$exists" ]]; then
                if [[ "$exists" == "true" ]] && [[ -n "$actual" ]] && [[ "$actual" != "null" ]]; then
                    echo -e "${GREEN}  ✓ Assertion passed: $path exists${NC}"
                    return 0
                elif [[ "$exists" == "false" ]] && ([[ -z "$actual" ]] || [[ "$actual" == "null" ]]); then
                    echo -e "${GREEN}  ✓ Assertion passed: $path does not exist${NC}"
                    return 0
                else
                    echo -e "${RED}  ✗ Assertion failed: $path existence check${NC}"
                    return 1
                fi
            fi
            
            if [[ -n "$expected_value" ]]; then
                if [[ "$actual" == "$expected_value" ]]; then
                    echo -e "${GREEN}  ✓ Assertion passed: $path = $expected_value${NC}"
                    return 0
                else
                    echo -e "${RED}  ✗ Assertion failed: $path expected '$expected_value', got '$actual'${NC}"
                    return 1
                fi
            fi
            
            if [[ -n "$contains" ]]; then
                if [[ "$actual" == *"$contains"* ]]; then
                    echo -e "${GREEN}  ✓ Assertion passed: $path contains '$contains'${NC}"
                    return 0
                else
                    echo -e "${RED}  ✗ Assertion failed: $path does not contain '$contains'${NC}"
                    return 1
                fi
            fi
            ;;
        *)
            echo -e "${YELLOW}  ⚠ Unknown assertion type: $type${NC}"
            return 0
            ;;
    esac
}

# Generate report
generate_report() {
    local report_file="$RESULTS_DIR/${SUITE}_${ENV}_$(date +%Y%m%d_%H%M%S).txt"
    
    {
        echo "=========================================="
        echo "Test Report: $SUITE"
        echo "Environment: $ENV"
        echo "Date: $(date '+%Y-%m-%d %H:%M:%S')"
        echo "=========================================="
        echo ""
        echo "Total Tests: $TOTAL_TESTS"
        echo "Passed: $PASSED_TESTS"
        echo "Failed: $FAILED_TESTS"
        echo "Skipped: $SKIPPED_TESTS"
        echo ""
        
        if [[ $FAILED_TESTS -eq 0 ]]; then
            echo "Result: ✓ ALL TESTS PASSED"
        else
            echo "Result: ✗ SOME TESTS FAILED"
        fi
    } > "$report_file"
    
    echo -e "${BLUE}Report saved to: $report_file${NC}"
}

# Main execution
main() {
    if [[ "$DEBUG" == true ]]; then
        echo "DEBUG: Starting main function" >&2
    fi
    
    print_header
    
    if [[ "$DEBUG" == true ]]; then
        echo "DEBUG: After print_header" >&2
    fi
    
    # Read test suite
    if [[ "$DEBUG" == true ]]; then
        echo "DEBUG: Reading test suite from: $SUITE_CONFIG" >&2
    fi
    
    local tests=$(jq -c '.tests[]' "$SUITE_CONFIG")
    
    if [[ "$DEBUG" == true ]]; then
        echo "DEBUG: Tests loaded, count: $(echo "$tests" | wc -l)" >&2
    fi
    
    # Filter by test ID if specified
    if [[ -n "$TEST_ID" ]]; then
        tests=$(echo "$tests" | jq -c "select(.id == \"$TEST_ID\")")
        if [[ -z "$tests" ]]; then
            echo -e "${RED}Error: Test ID not found: $TEST_ID${NC}"
            exit 1
        fi
    fi
    
    # Execute tests
    while IFS= read -r test; do
        execute_test "$test"
        echo ""
    done <<< "$tests"
    
    # Print summary
    echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║${NC}  Test Summary                                                ${BLUE}║${NC}"
    echo -e "${BLUE}╠════════════════════════════════════════════════════════════════╣${NC}"
    echo -e "${BLUE}║${NC}  Total:   $TOTAL_TESTS"
    echo -e "${BLUE}║${NC}  ${GREEN}Passed:  $PASSED_TESTS${NC}"
    
    if [[ $FAILED_TESTS -gt 0 ]]; then
        echo -e "${BLUE}║${NC}  ${RED}Failed:  $FAILED_TESTS${NC}"
    else
        echo -e "${BLUE}║${NC}  Failed:  $FAILED_TESTS"
    fi
    
    if [[ $SKIPPED_TESTS -gt 0 ]]; then
        echo -e "${BLUE}║${NC}  ${YELLOW}Skipped: $SKIPPED_TESTS${NC}"
    fi
    
    echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
    
    # Generate report if requested
    if [[ "$REPORT" == true ]]; then
        echo ""
        generate_report
    fi
    
    # Cleanup temp files
    rm -f "$TEMP_RESPONSE" "$TEMP_HEADERS" "$TEST_RESULTS_FILE"
    
    # Exit with appropriate code
    if [[ $FAILED_TESTS -gt 0 ]]; then
        exit 1
    else
        exit 0
    fi
}

# Run main
main