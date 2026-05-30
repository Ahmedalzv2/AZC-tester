FROM python:3.11-slim

WORKDIR /root/apps/backtest-lab

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY . /root/apps/backtest-lab

EXPOSE 3015

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "3015"]
