# Small, current Python base. The code uses 3.10+ syntax (e.g. `str | None`).
FROM python:3.12-slim

# No .pyc files; unbuffered stdout so logs show up live in `docker logs`.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps first so this layer is cached unless requirements change.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code. .dockerignore keeps secrets/state out of the image.
COPY . .

CMD ["python", "bot.py"]
