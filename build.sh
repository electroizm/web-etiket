#!/usr/bin/env bash
# Render.com build hook — her deploy'da çalışır.
# render.yaml -> services[*].buildCommand: ./build.sh
#
# Yaptıkları:
#   1. Bağımlılıkları kur
#   2. Static dosyaları topla (whitenoise için)
#   3. Django sistem tablolarını migrate et (sessions cookie'de ama
#      auth/contenttypes hala lazım — sqlite container içinde tutar)
set -o errexit  # herhangi bir adım başarısız olursa deploy fail olsun

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate --no-input
