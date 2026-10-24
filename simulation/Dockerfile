FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir flask numpy pandas

COPY app.py .

EXPOSE 8080

CMD [ "python","app.py" ]