FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --upgrade pip && \
    pip install --prefix=/install --no-cache-dir -r requirements.txt


FROM python:3.11-slim AS runtime

WORKDIR /app

COPY --from=builder /install /usr/local

# Copy application source
COPY agents/       ./agents/
COPY fonts/        ./fonts/
COPY state.py      .
COPY graph.py      .
COPY pdf_builder.py .
COPY run.py        .


ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

CMD ["python", "run.py", "--auto"]