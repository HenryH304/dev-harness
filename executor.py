#!/usr/bin/env python3
"""Host-side ralph executor for DevHarness.

Run this on the host machine (not in Docker). It subscribes to the Redis
`ralph:spawn` channel, executes ralph locally for each request, and publishes
the exit code back so the container can complete or fail the ticket.

Usage:
    python3 executor.py [redis_url]

Default redis_url: redis://localhost:6379
"""

import asyncio
import json
import logging
import subprocess
import sys

import redis.asyncio as aioredis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [executor] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

REDIS_URL = sys.argv[1] if len(sys.argv) > 1 else "redis://localhost:6379"


async def handle_request(client: aioredis.Redis, request: dict) -> None:
    """Run ralph for one spawn request and publish the result."""
    request_id = request.get("request_id", "unknown")
    cwd = request.get("cwd", "")
    timeout = int(request.get("timeout", 600))
    response_channel = request.get("response_channel", f"ralph:result:{request_id}")

    timeout_minutes = max(1, timeout // 60)
    log.info("spawn request_id=%s cwd=%s timeout=%dm", request_id, cwd, timeout_minutes)

    exit_code = 1
    try:
        proc = subprocess.Popen(
            ["ralph", "-timeout", f"{timeout_minutes}m"],
            cwd=cwd,
        )
        log.info("ralph started pid=%d request_id=%s", proc.pid, request_id)

        await client.publish(
            response_channel,
            json.dumps({"type": "ack", "request_id": request_id, "pid": proc.pid}),
        )

        try:
            exit_code = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, proc.wait),
                timeout=timeout + 30,
            )
        except asyncio.TimeoutError:
            proc.kill()
            log.warning("ralph timed out and was killed: request_id=%s pid=%d", request_id, proc.pid)

    except FileNotFoundError:
        log.error("ralph not found — is it on PATH?")
    except Exception as exc:
        log.error("spawn error request_id=%s: %s", request_id, exc)

    log.info("done request_id=%s exit_code=%d", request_id, exit_code)

    await client.publish(
        response_channel,
        json.dumps({"type": "result", "request_id": request_id, "exit_code": exit_code, "success": exit_code == 0}),
    )


async def main() -> None:
    client = aioredis.from_url(REDIS_URL)
    pubsub = client.pubsub()
    await pubsub.subscribe("ralph:spawn")
    log.info("connected to %s — listening on ralph:spawn", REDIS_URL)

    while True:
        message = await pubsub.get_message(
            ignore_subscribe_messages=True, timeout=1.0
        )
        if message is None:
            await asyncio.sleep(0.05)
            continue
        try:
            request = json.loads(message["data"])
        except Exception as exc:
            log.warning("failed to parse message: %s", exc)
            continue
        asyncio.create_task(handle_request(client, request))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("executor stopped")
