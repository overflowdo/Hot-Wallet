FROM python:3.12-slim

RUN pip install zmq python-bitcoinlib

WORKDIR /app

COPY listener.py .

CMD ["python", "listener.py"]