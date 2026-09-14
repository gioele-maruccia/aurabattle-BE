# ⚠️ PROMEMORIA: Test API in Locale

## 🎯 USARE SEMPRE PRIMA DI MODIFICHE/DEPLOY!

Hai a disposizione un sistema completo per testare le API in locale **SENZA rischiare di modificare il DB dev**!

## 🚀 Quick Start

```powershell
cd scripts\local-testing

# Setup iniziale (prima volta)
.\quick-test.ps1 setup

# Esporta dati dal dev (READ-ONLY)
.\quick-test.ps1 export

# Test interattivo (FACILE)
.\quick-test.ps1 interactive

# Test diretto
.\quick-test.ps1 test -Lambda user-api/update-profile -Event events/test.json -LoadData
```

## 📖 Documentazione Completa

Leggi [scripts/local-testing/README.md](scripts/local-testing/README.md) per:
- Esempi dettagliati
- Troubleshooting
- Best practices
- Configurazione avanzata

## 🔐 Garanzie di Sicurezza

- ✅ Export dati: **SOLO lettura** dal DB dev
- ✅ Test: **ZERO connessione** ad AWS (usa moto mock)
- ✅ DB dev: **MAI modificato**

## 💡 Workflow Consigliato

1. **Prima di sviluppare**: Esporta dati freschi
2. **Durante sviluppo**: Testa in locale con dati reali
3. **Trova e fixa bug**: Itera senza paura
4. **Prima del deploy**: Test finale con dati aggiornati
5. **Deploy**: Con fiducia! 🚀

---

**🎯 RICORDA**: Ogni volta che modifichi un'API o vuoi testare qualcosa, usa questo sistema!

👉 [scripts/local-testing/README.md](scripts/local-testing/README.md)
