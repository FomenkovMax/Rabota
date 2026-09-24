# Образ с браузером на борту: три банка из пяти читаются только им.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

# Корневой сертификат НУЦ Минцифры. Без него не открываются psbank.ru и
# другие сайты, выпустившие сертификат у Минцифры: стандартный набор
# корней его не содержит.
COPY certs/ /usr/local/share/ca-certificates/russian/
RUN cd /usr/local/share/ca-certificates/russian \
    && for f in *.pem; do mv "$f" "${f%.pem}.crt"; done \
    && update-ca-certificates

# Chromium читает свой набор корней, системный ему не указ, поэтому
# сертификат добавляем ещё и в хранилище NSS.
RUN apt-get update && apt-get install -y --no-install-recommends libnss3-tools \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /root/.pki/nssdb \
    && certutil -d sql:/root/.pki/nssdb -N --empty-password || true \
    && for f in /usr/local/share/ca-certificates/russian/*.crt; do \
         certutil -d sql:/root/.pki/nssdb -A -t "C,," -n "$(basename "$f")" -i "$f" || true; \
       done

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Данные и выгрузки держим на томе, чтобы история пережила пересборку.
VOLUME ["/app/data"]

CMD ["python", "run.py", "bot"]
