# 1. Offizielles, schlankes Python-Image nutzen
FROM python:3.11-slim

# 2. Arbeitsverzeichnis im Container festlegen
WORKDIR /app

# 3. System-Abhängigkeiten minimieren und Cache bereinigen
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 4. Anforderungen kopieren und installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Den restlichen Quellcode in den Container kopieren
COPY . .

# 6. Netzwerk-Port für Flask öffnen
EXPOSE 5000

# 7. Die App über das produktionsbereite Modul starten
CMD ["python", "app.py"]

