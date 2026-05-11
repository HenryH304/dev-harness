-include .env
export

.PHONY: up down start stop restart logs executor start-executor stop-executor start-ngrok stop-ngrok help

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  up           Build and start all services + expose via ngrok"
	@echo "  down         Stop ngrok and all services"
	@echo "  start        Build and start Docker services (tails logs)"
	@echo "  stop         Stop Docker services"
	@echo "  restart      Stop then start Docker services (tails logs)"
	@echo "  logs         Tail logs from all Docker services"
	@echo "  executor     Run the executor in the foreground (Ctrl-C to stop)"
	@echo "  start-ngrok  Start ngrok tunnel on port 8080 (prints public URL)"
	@echo "  stop-ngrok   Stop ngrok"
	@echo "  help         Show this help"

up: start-services start-executor start-ngrok
	@echo "Frontend: http://localhost:8080"
	@echo "Backend:  http://localhost:9080"
	@URL=$$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | python3 -c "import sys,json; t=json.load(sys.stdin).get('tunnels',[]); print(t[0]['public_url'] if t else '')" 2>/dev/null); \
	if [ -n "$$URL" ]; then echo "Public URL: $$URL"; else echo "Public URL: (ngrok not running — check /tmp/ngrok.log)"; fi
	docker-compose logs -f

down: stop-ngrok stop

start-services:
	docker-compose up -d --build

start: start-services start-executor
	@echo "Frontend: http://localhost:8080"
	@echo "Backend:  http://localhost:9080"
	@URL=$$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | python3 -c "import sys,json; t=json.load(sys.stdin).get('tunnels',[]); print(t[0]['public_url'] if t else '')" 2>/dev/null); \
	if [ -n "$$URL" ]; then echo "Public URL: $$URL"; else echo "Public URL: (ngrok not running — run make start-ngrok)"; fi
	docker-compose logs -f

stop: stop-executor
	docker-compose down

restart: stop start

logs:
	docker-compose logs -f

executor:
	@echo "Starting host-side ralph executor (Ctrl-C to stop)..."
	.venv/bin/python3 executor.py

start-executor:
	@if [ -f /tmp/executor.pid ] && kill -0 $$(cat /tmp/executor.pid) 2>/dev/null; then \
		echo "executor already running (pid=$$(cat /tmp/executor.pid))"; \
	else \
		nohup .venv/bin/python3 executor.py > /tmp/executor.log 2>&1 & \
		echo $$! > /tmp/executor.pid; \
		echo "Executor started pid=$$! (logs: /tmp/executor.log)"; \
	fi

stop-executor:
	@if [ -f /tmp/executor.pid ]; then \
		PID=$$(cat /tmp/executor.pid); \
		kill $$PID 2>/dev/null && echo "executor stopped (pid=$$PID)" || echo "executor was not running"; \
		rm -f /tmp/executor.pid; \
	else \
		echo "executor was not running"; \
	fi

start-ngrok:
	@if pgrep -x ngrok > /dev/null; then \
		echo "ngrok already running"; \
	else \
		nohup ngrok http 8080 --log=stdout --basic-auth="$(AUTH_USER):$(AUTH_PASSWORD)" > /tmp/ngrok.log 2>&1 & \
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
