#!/bin/bash

#####################################################################
#         BEEZEY API TEST FRAMEWORK - SETUP SCRIPT                 #
#####################################################################

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

print_header() {
    echo ""
    echo -e "${CYAN}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}  Beezey API Test Framework Setup                            ${CYAN}║${NC}"
    echo -e "${CYAN}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

check_dependencies() {
    echo -e "${BLUE}[1/8]${NC} Checking dependencies..."
    
    local missing=()
    local all_ok=true
    
    for cmd in curl jq aws; do
        if command -v $cmd &> /dev/null; then
            echo -e "${GREEN}  ✓ $cmd${NC}"
        else
            echo -e "${RED}  ✗ $cmd (missing)${NC}"
            missing+=($cmd)
            all_ok=false
        fi
    done
    
    if [[ "$all_ok" == false ]]; then
        echo ""
        echo -e "${YELLOW}Please install missing dependencies:${NC}"
        for tool in "${missing[@]}"; do
            case $tool in
                curl)
                    echo -e "  ${YELLOW}curl:${NC} sudo apt-get install curl (or brew install curl)"
                    ;;
                jq)
                    echo -e "  ${YELLOW}jq:${NC} sudo apt-get install jq (or brew install jq)"
                    ;;
                aws)
                    echo -e "  ${YELLOW}aws-cli:${NC} pip install awscli"
                    ;;
            esac
        done
        echo ""
    fi
}

create_directory_structure() {
    echo -e "${BLUE}[2/8]${NC} Creating directory structure..."
    
    # Core directories
    mkdir -p config
    mkdir -p scripts
    mkdir -p results
    
    # Test suite directories
    mkdir -p test-suites/job-listings/payloads
    mkdir -p test-suites/bookings/payloads
    mkdir -p test-suites/companies/payloads
    
    echo -e "${GREEN}  ✓ Directory structure created${NC}"
}

make_scripts_executable() {
    echo -e "${BLUE}[3/8]${NC} Making scripts executable..."
    
    # Make all scripts executable
    chmod +x scripts/*.sh 2>/dev/null || true
    chmod +x run-tests.sh 2>/dev/null || true
    
    echo -e "${GREEN}  ✓ Scripts are executable${NC}"
}

create_gitignore() {
    echo -e "${BLUE}[4/8]${NC} Creating .gitignore..."
    
    cat > .gitignore <<'EOF'
# Authentication tokens (sensitive)
config/auth.json

# Test results
results/
*.log

# Temporary files
*.tmp
/tmp/
.proxy.pid

# OS files
.DS_Store
Thumbs.db

# IDE
.vscode/
.idea/
*.swp
*.swo
EOF
    
    echo -e "${GREEN}  ✓ .gitignore created${NC}"
}

create_auth_template() {
    echo -e "${BLUE}[5/8]${NC} Creating auth.json template..."
    
    if [[ -f "config/auth.json" ]]; then
        echo -e "${YELLOW}  ⊙ auth.json already exists, skipping${NC}"
        return
    fi
    
    cat > config/auth.json <<'EOF'
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
    
    echo -e "${GREEN}  ✓ auth.json template created${NC}"
}

create_env_template() {
    echo -e "${BLUE}[6/8]${NC} Checking environment configuration..."
    
    if [[ -f "config/env.dev.json" ]]; then
        # Check if it needs updating
        if grep -q "YOUR_API_ID" config/env.dev.json 2>/dev/null; then
            echo -e "${YELLOW}  ⚠ config/env.dev.json contains placeholder values${NC}"
            echo -e "${YELLOW}    Update with actual API Gateway URLs${NC}"
        else
            echo -e "${GREEN}  ✓ config/env.dev.json exists and looks configured${NC}"
        fi
        return
    fi
    
    # Create template
    cat > config/env.dev.json <<'EOF'
{
  "environment": "dev",
  "region": "eu-south-1",
  "cognito": {
    "users": {
      "region": "eu-south-1",
      "userPoolId": "eu-south-1_0oK9agPYd",
      "clientId": "79g67hnuepfuoh1fnk4d98jfpu"
    },
    "backoffice": {
      "region": "eu-south-1",
      "userPoolId": "eu-south-1_Vfr0FKYfO",
      "clientId": "6c3jgvgkk28uurt2qvqf697v5k"
    }
  },
  "apis": {
    "jobListings": {
      "baseUrl": "https://jrjgn9r6hj.execute-api.eu-south-1.amazonaws.com/dev",
      "stackName": "seasonal-jobs-joblistings-services-dev",
      "description": "Job listings management API"
    },
    "companies": {
      "baseUrl": "https://n4gq6fx4qd.execute-api.eu-south-1.amazonaws.com/dev",
      "stackName": "dev-companies-api",
      "description": "Company profile management API"
    },
    "userProfile": {
      "baseUrl": "https://7mld8ngu7f.execute-api.eu-south-1.amazonaws.com/dev",
      "stackName": "dev-user-profile-api",
      "description": "User profile and verification API"
    },
    "documents": {
      "baseUrl": "https://pri6vp5x27.execute-api.eu-south-1.amazonaws.com/dev",
      "stackName": "dev-documents-api",
      "description": "Document upload and management API"
    },
    "bookings": {
      "baseUrl": "https://f0xtalggll.execute-api.eu-south-1.amazonaws.com/dev",
      "stackName": "bookings-service-dev",
      "description": "Bookings management API"
    },
    "backoffice": {
      "baseUrl": "https://fp3nxfz7c4.execute-api.eu-south-1.amazonaws.com/dev",
      "stackName": "dev-backoffice-api",
      "description": "Backoffice operations API"
    }
  },
  "testUsers": {
    "company": {
      "username": "REPLACE_WITH_COMPANY_EMAIL",
      "description": "Primary company test user",
      "groups": ["companies"]
    },
    "company2": {
      "username": "REPLACE_WITH_COMPANY2_EMAIL",
      "description": "Secondary company for authorization tests",
      "groups": ["companies"]
    },
    "worker": {
      "username": "REPLACE_WITH_WORKER_EMAIL",
      "description": "Worker test user",
      "groups": ["workers"]
    },
    "backoffice": {
      "username": "REPLACE_WITH_BACKOFFICE_EMAIL",
      "description": "Backoffice operator",
      "groups": ["backoffice"]
    }
  },
  "s3": {
    "companiesBucket": "dev-beezey-companies-assets",
    "documentsBucket": "dev-beezey-documents-assets"
  },
  "dynamodb": {
    "companiesTable": "dev-Companies",
    "jobListingsTable": "dev-JobListings",
    "bookingsTable": "dev-Bookings"
  }
}
EOF
    
    echo -e "${GREEN}  ✓ config/env.dev.json template created${NC}"
    echo -e "${YELLOW}    → Update with your actual values${NC}"
}

create_payload_templates() {
    echo -e "${BLUE}[7/8]${NC} Creating payload templates..."
    
    # Companies payloads
    if [[ ! -f "test-suites/companies/payloads/create-company-valid.json" ]]; then
        cat > test-suites/companies/payloads/create-company-valid.json <<'EOF'
{
  "businessName": "KFC Belgium Test",
  "vatNumber": "BE0123456789"
}
EOF
    fi
    
    if [[ ! -f "test-suites/companies/payloads/update-company-description.json" ]]; then
        cat > test-suites/companies/payloads/update-company-description.json <<'EOF'
{
  "description": "Fast food chain dedicated to quality meals and excellent customer service",
  "location": {
    "city": "Mechelen",
    "country": "Belgium",
    "coordinates": {
      "lat": 51.0259,
      "lon": 4.4773
    }
  }
}
EOF
    fi
    
    # Job Listings payloads (if they don't exist)
    if [[ ! -f "test-suites/job-listings/payloads/create-listing-valid.json" ]]; then
        cat > test-suites/job-listings/payloads/create-listing-valid.json <<'EOF'
{
  "title": "Cameriere per stagione estiva",
  "description": "Cerchiamo cameriere motivato per la stagione estiva.",
  "startDate": "2025-06-01",
  "endDate": "2025-09-30",
  "positions": 3,
  "category": "Food & Beverage",
  "status": "published",
  "location": {
    "city": "Milano",
    "province": "MI",
    "country": "Italy"
  }
}
EOF
    fi
    
    echo -e "${GREEN}  ✓ Payload templates created${NC}"
}

print_summary() {
    echo -e "${BLUE}[8/8]${NC} Setup complete!"
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║${NC}  Setup Complete!                                              ${GREEN}║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${CYAN}Available Test Suites:${NC}"
    echo -e "  ${YELLOW}├─ job-listings${NC}  (Job listings management)"
    echo -e "  ${YELLOW}├─ companies${NC}      (Company profiles)"
    echo -e "  ${YELLOW}└─ bookings${NC}       (Booking management)"
    echo ""
    echo -e "${CYAN}Next Steps:${NC}"
    echo ""
    echo -e "${YELLOW}1. Update Configuration${NC}"
    echo "   Edit: ${BLUE}config/env.dev.json${NC}"
    echo "   - Replace test user email addresses"
    echo "   - Verify API Gateway URLs are correct"
    echo ""
    echo -e "${YELLOW}2. Get API Gateway URLs (if needed)${NC}"
    echo "   ${BLUE}# Companies API${NC}"
    echo "   aws cloudformation describe-stacks \\"
    echo "     --stack-name dev-companies-api \\"
    echo "     --query 'Stacks[0].Outputs[?OutputKey==\`CompaniesApiUrl\`].OutputValue' \\"
    echo "     --output text --region eu-south-1"
    echo ""
    echo "   ${BLUE}# Job Listings API${NC}"
    echo "   aws cloudformation describe-stacks \\"
    echo "     --stack-name seasonal-jobs-joblistings-services-dev \\"
    echo "     --query 'Stacks[0].Outputs[?OutputKey==\`JobListingsApiUrl\`].OutputValue' \\"
    echo "     --output text --region eu-south-1"
    echo ""
    echo -e "${YELLOW}3. Authenticate Test Users${NC}"
    echo "   ${BLUE}# Primary company user${NC}"
    echo "   ./scripts/auth-helper.sh login --type company --env dev"
    echo ""
    echo "   ${BLUE}# Secondary company user (for authorization tests)${NC}"
    echo "   ./scripts/auth-helper.sh login --type company2 --env dev"
    echo ""
    echo "   ${BLUE}# Worker user${NC}"
    echo "   ./scripts/auth-helper.sh login --type worker --env dev"
    echo ""
    echo -e "${YELLOW}4. Run Tests${NC}"
    echo "   ${BLUE}# Companies API (all tests)${NC}"
    echo "   ./run-tests.sh --suite companies --env dev"
    echo ""
    echo "   ${BLUE}# Companies API (specific test)${NC}"
    echo "   ./run-tests.sh --suite companies --test create-company-valid --env dev"
    echo ""
    echo "   ${BLUE}# Job Listings API${NC}"
    echo "   ./run-tests.sh --suite job-listings --env dev"
    echo ""
    echo "   ${BLUE}# With verbose output${NC}"
    echo "   ./run-tests.sh --suite companies --env dev --verbose"
    echo ""
    echo "   ${BLUE}# Generate report${NC}"
    echo "   ./run-tests.sh --suite companies --env dev --report"
    echo ""
    echo -e "${CYAN}Quick Start (Companies API):${NC}"
    echo "   1. Update config/env.dev.json with test user email"
    echo "   2. ./scripts/auth-helper.sh login --type company --env dev"
    echo "   3. ./run-tests.sh --suite companies --test create-company-valid --env dev --verbose"
    echo ""
    echo -e "${CYAN}Help & Documentation:${NC}"
    echo "   ./scripts/test-runner.sh --help"
    echo "   cat test-suites/companies/README.md"
    echo "   cat test-suites/job-listings/README.md"
    echo ""
    echo -e "${CYAN}Troubleshooting:${NC}"
    echo "   ${BLUE}# Check authentication status${NC}"
    echo "   jq '.dev' config/auth.json"
    echo ""
    echo "   ${BLUE}# Verify API connectivity${NC}"
    echo "   curl -s https://n4gq6fx4qd.execute-api.eu-south-1.amazonaws.com/dev/companies/public/test"
    echo ""
    echo "   ${BLUE}# View test results${NC}"
    echo "   ls -la results/"
    echo ""
}

main() {
    print_header
    check_dependencies
    create_directory_structure
    make_scripts_executable
    create_gitignore
    create_auth_template
    create_env_template
    create_payload_templates
    print_summary
}

# Run main
main