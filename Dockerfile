# TgCrypto 1.2.5 publishes a Linux wheel for CPython 3.10. Using that wheel
# keeps the runtime image small and avoids needing GCC during the build.
FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
