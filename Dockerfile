FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir -e ".[dev]"

COPY . .

EXPOSE 3010

CMD ["sh", "-c", "python manage.py migrate && python manage.py shell -c \"from demo.seed import reset_demo_state; reset_demo_state()\" && gunicorn config.wsgi:application --bind 0.0.0.0:3010"]
