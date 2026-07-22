FROM python:3.11-slim

WORKDIR /app

# Keep dependencies shared with the main backend to reduce duplication.
# (requirements.txt is already present at repo root of errandbridge-backend)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY ml/app /app

EXPOSE 8010

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8010"]
