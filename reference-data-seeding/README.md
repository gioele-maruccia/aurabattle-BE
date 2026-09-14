# 📚 Reference Data Seeding

Sistema di seeding configuration-driven per le tabelle di riferimento DynamoDB.

## 📁 Struttura

```
reference-data-seeding/
├── README.md                           # Questo file
├── config/                             # File di configurazione JSON
│   ├── README.md
│   ├── contracts_ccnl_turismo.json
│   ├── job_categories.json
│   ├── employment_types.json
│   ├── fipe_job_roles_catalog.json
│   └── italian-tax-data.json          # Tax data for net salary calculation
├── seed_all_tables.py                  # Script di seeding unificato
└── docs/                               # Documentazione

Note: ateco_categories.json is now in ../modules/common-beebusy/ (shared with frontend)
```

## 🚀 Quick Start

```bash
# Dry run
python seed_all_tables.py --environment dev --dry-run

# Seed tutte le tabelle
python seed_all_tables.py --environment dev

# Seed una tabella specifica
python seed_all_tables.py --environment dev --table contracts
```

## 📖 Documentazione

- [docs/BACKEND_INTEGRATION.md](docs/BACKEND_INTEGRATION.md) - Come integrare nel backend
- [docs/SEEDING_SOLUTION.md](docs/SEEDING_SOLUTION.md) - Panoramica della soluzione
- [docs/CONFIG_DRIVEN_GUIDE.md](docs/CONFIG_DRIVEN_GUIDE.md) - Guida completa
- [config/README.md](config/README.md) - Guida ai file di configurazione

## 🔧 Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Run dry-run
python seed_all_tables.py --environment dev --dry-run

# Seed all tables
python seed_all_tables.py --environment dev
```