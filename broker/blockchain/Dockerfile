FROM python:3.12-slim

WORKDIR /app

COPY broker.py .
COPY RicartAgrawala.py .
COPY blockchain/ ./blockchain/

RUN mkdir -p /data

ENV PYTHONUNBUFFERED=1

CMD ["python", "broker.py", "setor_a"]
