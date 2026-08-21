FROM python:3.12-slim

RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends ffmpeg tzdata ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Doimiy ishlaydigan ichki jadval — cron kerak emas
CMD ["python", "-m", "src.scheduler"]
