FROM python:3.12-slim

# Keep the repo-relative layout (api-python/ at /app): several modules use
# Path(__file__).parents[n] to locate the package root, which requires the
# api-python directory to live under a parent directory in the container.
WORKDIR /app
COPY . /app/api-python
WORKDIR /app/api-python

RUN pip install --no-cache-dir .

ENV PORT=8000
EXPOSE 8000

# Cloud Run injects the port via $PORT; local runs default to 8000.
CMD ["sh", "-c", "alembic -c alembic.ini upgrade head && exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
