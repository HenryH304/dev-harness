.PHONY: up down start stop restart logs start-ngrok stop-ngrok help

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  up           Build and start all services + expose via ngrok"
	@echo "  down         Stop ngrok and all services"
	@echo "  start        Build and start Docker services"
	@echo "  stop         Stop Docker services"
	@echo "  restart      Stop then start Docker services"
	@echo "  logs         Tail logs from all Docker services"
	@echo "  start-ngrok  Start ngrok tunnel on port 8080 (prints public URL)"
	@echo "  stop-ngrok   Stop ngrok"
	@echo "  help         Show this help"

up: start start-ngrok

down: stop-ngrok stop

start:
	docker-compose up -d --build
	@echo "Frontend: http://localhost:8080"
	@echo "Backend:  http://localhost:9080"
	@URL=$$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | python3 -c "import sys,json; t=json.load(sys.stdin).get('tunnels',[]); print(t[0]['public_url'] if t else '')" 2>/dev/null); \
	if [ -n "$$URL" ]; then echo "Public URL: $$URL"; fi

stop:
	docker-compose down

restart: stop start

logs:
	docker-compose logs -f

start-ngrok:
	@if pgrep -x ngrok > /dev/null; then \
		echo "ngrok already running"; \
	else \
		nohup ngrok http 8080 --log=stdout > /tmp/ngrok.log 2>&1 & \
		printf "Waiting for ngrok..."; \
		for i in 1 2 3 4 5 6 7 8 9 10; do \
			URL=$$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | python3 -c "import sys,json; t=json.load(sys.stdin).get('tunnels',[]); print(t[0]['public_url'] if t else '')" 2>/dev/null); \
			if [ -n "$$URL" ]; then \
				echo ""; \
				echo "Public URL: $$URL"; \
				exit 0; \
			fi; \
			printf "."; sleep 1; \
		done; \
		echo ""; echo "ngrok URL not available — check /tmp/ngrok.log"; \
	fi

stop-ngrok:
	@pkill -x ngrok && echo "ngrok stopped" || echo "ngrok was not running"
