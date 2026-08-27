FROM python:3.11-slim AS base

# Prevents Python from writing .pyc files and buffers -- cleaner container logs.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install deps in a separate layer so code changes don't invalidate the pip cache layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY workers ./workers
COPY alembic.ini .
COPY migrations ./migrations

# The API imports workers.tasks to call .delay() and enqueue jobs -- it needs
# the task module present even though it never executes tasks itself.
# alembic.ini + migrations/ let us run `alembic upgrade head` from inside
# this same container instead of needing a separate migration image.

# Run as non-root user
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
