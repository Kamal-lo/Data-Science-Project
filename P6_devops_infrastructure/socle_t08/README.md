# Plateforme IA - Marchés publics (socle)

    cp .env.example .env
    docker compose up --build

Vérifications :
- http://localhost:8000/health  -> {"db": true, "redis": true}
- http://localhost:8000/docs
- POST /debug/ping              -> {"result": "pong"}
