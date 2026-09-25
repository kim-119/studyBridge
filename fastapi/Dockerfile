FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    fonts-nanum \
    tesseract-ocr \
    tesseract-ocr-kor \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
COPY main.py .
COPY agent_quality_policy.py .
COPY agent_feedback_policy.py .
COPY rag.py .

RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
