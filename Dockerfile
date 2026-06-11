FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Taipei

WORKDIR /app
COPY . /app
RUN mkdir -p /app/seed && cp -a /app/data/. /app/seed/

EXPOSE 10000
CMD ["python", "cloud_entry.py"]
