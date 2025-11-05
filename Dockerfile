FROM python:3.11-slim
RUN apt-get update && apt-get install -y build-essential libc6-dev libnss3 libatk1.0-0 libgtk-3-0 libxss1 libasound2 curl
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
# OPTIONAL: install playwright browsers
RUN python -m playwright install chromium
CMD ["python", "app.py"]
