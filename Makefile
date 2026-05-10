.PHONY: up down start stop restart logs start-ngrok stop-ngrok

up: start start-ngrok

down: stop-ngrok stop

start:
	docker-compose up -d --build
	@echo "Frontend: http://localhost:8080"
	@echo "Backend:  http://localhost:9080"

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
