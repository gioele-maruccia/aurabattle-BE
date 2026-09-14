#!/bin/bash

# Check environment setup for testing

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║${NC}  Environment Check                                            ${BLUE}║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# If script is in scripts/ subdirectory, go up one level
if [[ "$(basename "$SCRIPT_DIR")" == "scripts" ]]; then
    PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
else
    PROJECT_ROOT="$SCRIPT_DIR"
fi

echo -e "${BLUE}Current directory:${NC} $(pwd)"
echo -e "${BLUE}Script location:${NC} $SCRIPT_DIR"
echo -e "${BLUE}Project root:${NC} $PROJECT_ROOT"
echo ""

# Check dependencies
echo -e "${BLUE}Checking dependencies...${NC}"
for cmd in curl jq aws; do
    if command -v $cmd &> /dev/null; then
        version=$($cmd --version 2>&1 | head -n1)
        echo -e "${GREEN}  ✓ $cmd${NC} - $version"
    else
        echo -e "${RED}  ✗ $cmd (not found)${NC}"
    fi
done
echo ""

# Check directory structure
echo -e "${BLUE}Checking directory structure...${NC}"
for dir in config test-suites scripts results; do
    if [[ -d "$SCRIPT_DIR/$dir" ]]; then
        echo -e "${GREEN}  ✓ $dir/${NC}"
    else
        echo -e "${RED}  ✗ $dir/ (missing)${NC}"
    fi
done
echo ""

# Check config files
echo -e "${BLUE}Checking configuration files...${NC}"
for file in config/env.dev.json config/auth.json; do
    if [[ -f "$SCRIPT_DIR/$file" ]]; then
        echo -e "${GREEN}  ✓ $file${NC}"
        if [[ "$file" == "config/env.dev.json" ]]; then
            if grep -q "YOUR_API_ID" "$SCRIPT_DIR/$file" 2>/dev/null; then
                echo -e "${YELLOW}    ⚠ Contains placeholder values (YOUR_API_ID)${NC}"
            fi
        fi
    else
        echo -e "${RED}  ✗ $file (missing)${NC}"
    fi
done
echo ""

# Check scripts
echo -e "${BLUE}Checking scripts...${NC}"
for script in scripts/test-runner.sh scripts/auth-helper.sh scripts/utils.sh; do
    if [[ -f "$SCRIPT_DIR/$script" ]]; then
        if [[ -x "$SCRIPT_DIR/$script" ]]; then
            echo -e "${GREEN}  ✓ $script (executable)${NC}"
        else
            echo -e "${YELLOW}  ⚠ $script (not executable)${NC}"
            echo -e "${YELLOW}    Run: chmod +x $SCRIPT_DIR/$script${NC}"
        fi
    else
        echo -e "${RED}  ✗ $script (missing)${NC}"
    fi
done
echo ""

# Check test suites
echo -e "${BLUE}Checking test suites...${NC}"
if [[ -d "$SCRIPT_DIR/test-suites" ]]; then
    suite_count=$(find "$SCRIPT_DIR/test-suites" -name "suite.json" | wc -l)
    echo -e "  Found ${GREEN}$suite_count${NC} test suite(s):"
    find "$SCRIPT_DIR/test-suites" -name "suite.json" -exec dirname {} \; | while read -r suite_dir; do
        suite_name=$(basename "$suite_dir")
        payload_count=$(find "$suite_dir/payloads" -name "*.json" 2>/dev/null | wc -l)
        echo -e "${GREEN}    ✓ $suite_name${NC} ($payload_count payloads)"
    done
else
    echo -e "${RED}  ✗ test-suites/ directory not found${NC}"
fi
echo ""

# Test jq on config files
echo -e "${BLUE}Testing JSON parsing...${NC}"
if [[ -f "$SCRIPT_DIR/config/env.dev.json" ]]; then
    if jq empty "$SCRIPT_DIR/config/env.dev.json" 2>/dev/null; then
        echo -e "${GREEN}  ✓ env.dev.json is valid JSON${NC}"
        
        # Try to extract API URL
        api_url=$(jq -r '.apis.jobListings.baseUrl // empty' "$SCRIPT_DIR/config/env.dev.json" 2>/dev/null)
        if [[ -n "$api_url" ]]; then
            echo -e "    API URL: $api_url"
        fi
    else
        echo -e "${RED}  ✗ env.dev.json has invalid JSON${NC}"
    fi
fi

if [[ -f "$SCRIPT_DIR/test-suites/job-listings/suite.json" ]]; then
    if jq empty "$SCRIPT_DIR/test-suites/job-listings/suite.json" 2>/dev/null; then
        test_count=$(jq '.tests | length' "$SCRIPT_DIR/test-suites/job-listings/suite.json" 2>/dev/null)
        echo -e "${GREEN}  ✓ job-listings/suite.json is valid JSON${NC}"
        echo -e "    Test cases: $test_count"
    else
        echo -e "${RED}  ✗ job-listings/suite.json has invalid JSON${NC}"
    fi
fi
echo ""

# Summary
echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║${NC}  Summary                                                      ${BLUE}║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"

if command -v curl &>/dev/null && command -v jq &>/dev/null && command -v aws &>/dev/null; then
    if [[ -f "$SCRIPT_DIR/config/env.dev.json" ]] && [[ -f "$SCRIPT_DIR/test-suites/job-listings/suite.json" ]]; then
        echo -e "${GREEN}✓ Environment looks good!${NC}"
        echo ""
        echo -e "${BLUE}Next steps:${NC}"
        echo -e "  1. Ensure config/env.dev.json has real API URLs"
        echo -e "  2. Login: ${YELLOW}./scripts/auth-helper.sh login --type company --env dev${NC}"
        echo -e "  3. Run tests: ${YELLOW}./scripts/test-runner.sh --suite job-listings --env dev --verbose${NC}"
    else
        echo -e "${YELLOW}⚠ Missing some configuration files${NC}"
        echo -e "  Run: ${YELLOW}./setup.sh${NC}"
    fi
else
    echo -e "${RED}✗ Missing required dependencies${NC}"
    echo -e "  Install: curl, jq, aws-cli"
fi
echo ""