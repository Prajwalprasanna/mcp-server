FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

# Render injects its own PORT env var — server.py already reads PORT from environment
EXPOSE 8000

CMD ["python", "server.py"]
