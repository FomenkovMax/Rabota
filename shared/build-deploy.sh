#!/bin/sh
# Собирает каталог для публикации: обе страницы, общий движок и лендинг.
# Запускать из корня репозитория:  sh shared/build-deploy.sh
#
# Каталог называется tribute-dist и лежит в .gitignore — это артефакт сборки.
# Корневой netlify.toml принадлежит лендингу «ЛИФТ» и собирает Vite-проект,
# поэтому на время публикации его нужно подменить (см. README).
set -eu

OUT=tribute-dist
rm -rf "$OUT"
mkdir -p "$OUT"

cp -r kaneki guts shared "$OUT"/
cp shared/landing/index.html "$OUT"/index.html

# в публикацию не едут инструменты и документация
rm -rf "$OUT"/shared/landing "$OUT"/shared/README.md "$OUT"/shared/frames.cjs "$OUT"/shared/build-deploy.sh

printf '%s: %s\n' "$OUT" "$(du -sh "$OUT" | cut -f1)"
