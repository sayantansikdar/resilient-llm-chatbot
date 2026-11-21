.PHONY: up down logs ps test dev-backend dev-frontend clean

up:
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example - put your real API keys in it")
	docker compose up -d --build
	@echo ""
	@echo "  frontend  http://localhost:3000"
	@echo "  backend   http://localhost:8000  (health: http://localhost:8000/health)"

down:
	docker compose down

logs:
	docker compose logs -f

ps:
	docker compose ps

test:
	cd backend && python -m pytest -q

dev-backend:
	cd backend && uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && npm run dev

# also removes the SQLite volume
clean:
	docker compose down -v
