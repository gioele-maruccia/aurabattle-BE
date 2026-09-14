# Profile Upgrade Documents Scripts

## 🚀 Setup Automatico (Una Riga!)

### Windows (PowerShell)
```powershell
.\deploy.ps1 -Environment dev
```

### Mac/Linux (Bash)
```bash
chmod +x deploy.sh test-upload.sh
./deploy.sh dev
```

Questo script:
- ✅ Deploya CloudFormation stack
- ✅ Configura S3 event notifications automaticamente
- ✅ Verifica che tutto sia corretto

## 🧪 Test

### Windows
```powershell
.\test-upload.ps1 -Environment dev
```

### Mac/Linux
```bash
./test-upload.sh dev
```

## 📖 Documentazione Completa

Leggi: `docs/02_architecture/PROFILE_UPLOAD_DOCUMENTS.md`

Contiene:
- ✅ Come funziona il flusso
- ✅ Schema DynamoDB
- ✅ Troubleshooting
- ✅ Configurazione ambiente

---

**That's it! Deploy in one command.** 🎉
