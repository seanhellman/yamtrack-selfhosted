# python:3.12-slim is multi-arch (includes linux/arm64), so this builds and
# runs natively on the Oracle Ampere (ARM) instance, same as the other services.
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first so this layer is cached unless requirements change.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py queries.py ./
COPY templates ./templates

EXPOSE 8090

# waitress is a production WSGI server; app:app = the `app` Flask object in app.py.
CMD ["waitress-serve", "--host=0.0.0.0", "--port=8090", "app:app"]
