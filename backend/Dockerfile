FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# Trust all directories on the shared project volume — the container runs as
# root but the host volume is owned by henry, triggering git's dubious-ownership
# check. '*' is safe here because this container only runs internal tooling.
RUN git config --system safe.directory '*'

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9080"]
