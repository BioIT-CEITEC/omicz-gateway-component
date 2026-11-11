# Local S3 server for the demo (moto). It keeps every object in memory, so use it only
# for the small example runs, not for large transfers.
FROM python:3.13-slim
RUN pip install --no-cache-dir "moto[server]==5.1.4"
EXPOSE 5000
CMD ["moto_server", "-H", "0.0.0.0", "-p", "5000"]
