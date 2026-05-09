#!/usr/bin/env bash
# Render.com build hook — her deploy'da çalışır.
#
# Yaptıkları:
#   1) Pip + bağımlılıklar
#   2) Static dosyaları topla (whitenoise üretimde tek başına serve edecek)
#   3) Django sistem tabloları (auth, contenttypes, vs.) — sqlite container
#      içinde; signed-cookie session kullandığımız için kalıcılık şart değil
set -o errexit  # adımlardan biri başarısız olursa deploy fail

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate --no-input
