FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
COPY wordlists /app/wordlists

RUN pip install --no-cache-dir -r requirements.txt

COPY ai-backend ./ai-backend
COPY api.py .
COPY frontend_build ./frontend_build

EXPOSE 8000
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
