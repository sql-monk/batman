# docker build -t batman -f deploy/Dockerfile . && docker run --network host -v batman-data:/app/data -v $PWD/config.toml:/app/config.toml batman
# network_mode host обов'язковий: mDNS і UDP-broadcast через NAT не працюють.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY batman_service ./batman_service
COPY migrations ./migrations
ENV BATMAN_CONFIG=/app/config.toml
EXPOSE 8000
CMD ["python", "-m", "batman_service"]
