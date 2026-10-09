FROM python:3.10-slim

WORKDIR /app

# Install system C compilers and OpenLDAP development libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    libldap2-dev \
    libsasl2-dev \
    ldap-utils \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy app files
COPY . .

EXPOSE 5000

CMD ["python", "app.py"]