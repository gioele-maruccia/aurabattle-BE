# 4SeasonsJob API - Swagger UI Documentation

Simple launcher for Swagger UI with authentication proxy supporting dev/prod environments.

## Quick Start

### Prerequisites

- **Docker** - [Download](https://docs.docker.com/get-docker/)
- **Node.js** - [Download](https://nodejs.org/)
- **AWS CLI** (configured) - [Download](https://aws.amazon.com/cli/)

### Bundle Swagger

Before launching, bundle the swagger files:

```bash
npx @redocly/cli bundle swagger.yml -o swagger-bundled.yml
```

### Launch

```bash
# Start dev environment
./launch-swagger.sh dev

# Start prod environment  
./launch-swagger.sh prod

# Stop all
./launch-swagger.sh stop
```

Browser opens automatically at `http://localhost:8080`

## How to Authenticate

1. **Login** - Use `POST /auth/login/users`
2. **Copy token** - Get `idToken` from response
3. **Authorize** - Click 🔓 button and paste token
4. **Test APIs** - All endpoints now work

Token expires in 1 hour - re-login to refresh.

## Environments

**Dev:**
- Cognito Pool: `eu-south-1_0oK9agPYd`
- APIs: All dev endpoints

**Prod:**
- Cognito Pool: `eu-south-1_iCBtUlJO6`
- APIs: Production endpoints (where configured)

## Main APIs

- `/auth/login/*` - Authentication
- `/contracts/calculate-base-pay` - CCNL salary calculations
- `/reference-data` - Job roles, contracts, categories
- `/companies/*` - Company management
- `/listings/*` - Job listings
- `/bookings/*` - Bookings & applications

## Troubleshooting

**Port already in use?**
```bash
./launch-swagger.sh stop
./launch-swagger.sh dev
```

**Check logs:**
```bash
tail -f proxy-dev.log
```

**Docker issues:**
```bash
docker ps
docker logs swagger-ui-docs-dev
```

---

**Access:** http://localhost:8080 (Swagger UI) | http://localhost:8081 (Proxy)