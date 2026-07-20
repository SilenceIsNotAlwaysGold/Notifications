#!/usr/bin/env bash
set -euo pipefail

SDK_URL="https://wwcdn.weixin.qq.com/node/wwcomm/sdk_x86_v3_20250205.tgz"
SDK_SHA256="afa8c017da2994ad2215933f2fcc6042d40d935663ad42d6e1e9d7716652f0d8"
SDK_MD5="f2db3dd1372c516db6290afbd1b5c698"
TARGET_DIR="${1:-wecom_archive_sidecar/sdk}"

archive="$(mktemp)"
extract_dir="$(mktemp -d)"
cleanup() {
  rm -f "$archive"
  rm -rf "$extract_dir"
}
trap cleanup EXIT

curl --fail --location --silent --show-error --max-time 120 "$SDK_URL" --output "$archive"

if command -v sha256sum >/dev/null 2>&1; then
  actual_sha256="$(sha256sum "$archive" | awk '{print $1}')"
else
  actual_sha256="$(shasum -a 256 "$archive" | awk '{print $1}')"
fi
if [[ "$actual_sha256" != "$SDK_SHA256" ]]; then
  echo "SDK archive SHA256 mismatch" >&2
  exit 1
fi

tar -xzf "$archive" -C "$extract_dir"
library="$extract_dir/C_sdk/libWeWorkFinanceSdk_C.so"
if command -v md5sum >/dev/null 2>&1; then
  actual_md5="$(md5sum "$library" | awk '{print $1}')"
else
  actual_md5="$(md5 -q "$library")"
fi
if [[ "$actual_md5" != "$SDK_MD5" ]]; then
  echo "SDK library MD5 mismatch" >&2
  exit 1
fi

install -d -m 0755 "$TARGET_DIR"
install -m 0755 "$library" "$TARGET_DIR/libWeWorkFinanceSdk_C.so"
install -m 0644 "$extract_dir/C_sdk/WeWorkFinanceSdk_C.h" "$TARGET_DIR/WeWorkFinanceSdk_C.h"
install -m 0644 "$extract_dir/C_sdk/version.txt" "$TARGET_DIR/version.txt"

echo "Installed WeCom Finance SDK $(tr -d '\r\n' < "$TARGET_DIR/version.txt") to $TARGET_DIR"
