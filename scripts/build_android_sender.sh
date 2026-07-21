#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="${1:-${project_root}/dist/android-sender}"
build_platform="${ANDROID_BUILD_PLATFORM:-linux/amd64}"

mkdir -p "${output_dir}"
docker build \
  --platform "${build_platform}" \
  --target artifacts \
  --output "type=local,dest=${output_dir}" \
  "${project_root}/android_sender_client"

artifact_name="zhihe-wecom-sender-debug.apk"
if command -v sha256sum >/dev/null 2>&1; then
  (cd "${output_dir}" && sha256sum "${artifact_name}" > SHA256SUMS)
else
  (cd "${output_dir}" && shasum -a 256 "${artifact_name}" > SHA256SUMS)
fi

printf 'Android sender artifacts: %s\n' "${output_dir}"
