#!/usr/bin/env bash
set -euo pipefail

project_dir="${LEGAL_WECOM_PROJECT_DIR:-/opt/legal-wecom-automation}"
env_file="${LEGAL_WECOM_ENV_FILE:-${project_dir}/.env}"
python_binary="${LEGAL_WECOM_PYTHON:-${project_dir}/.venv/bin/python}"

if [[ ! -r "${env_file}" ]]; then
  echo "Android sender env file is not readable: ${env_file}" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${env_file}"
set +a

serial="${WECOM_ANDROID_SERIAL:-127.0.0.1:5555}"
adb_binary="${WECOM_ANDROID_ADB_BINARY:-adb}"
host_port="${WECOM_SENDER_PORT:-8092}"
device_port="${WECOM_ANDROID_DEVICE_PORT:-8092}"
wait_attempts="${WECOM_ANDROID_BOOT_WAIT_ATTEMPTS:-60}"

for ((attempt = 1; attempt <= wait_attempts; attempt += 1)); do
  "${adb_binary}" connect "${serial}" >/dev/null 2>&1 || true
  if [[ "$("${adb_binary}" -s "${serial}" get-state 2>/dev/null || true)" == "device" ]] \
    && [[ "$("${adb_binary}" -s "${serial}" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == "1" ]]; then
    break
  fi
  if ((attempt == wait_attempts)); then
    echo "Android sender device did not become ready: ${serial}" >&2
    exit 1
  fi
  sleep 2
done

"${python_binary}" -m wecom_sender_sidecar.device_cli \
  --serial "${serial}" \
  --adb-binary "${adb_binary}" \
  configure \
  --host-port "${host_port}" \
  --device-port "${device_port}"

"${adb_binary}" -s "${serial}" shell am start \
  -n com.tencent.wework/.launch.LaunchSplashActivity >/dev/null

echo "Android sender runtime restored for ${serial}"
