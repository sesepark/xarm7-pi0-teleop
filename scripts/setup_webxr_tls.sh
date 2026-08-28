#!/usr/bin/env bash
# Generate a project-local CA and an HTTPS server certificate for WebXR.
# The CA key never leaves this PC. Only webxr-local-ca.crt is installed on a phone.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TLS_DIR="$PROJECT_ROOT/runtime/webxr_tls"
mkdir -p "$TLS_DIR"

LAN_IP="$(ip -4 route get 1.1.1.1 | awk '{for (i=1; i<=NF; i++) if ($i == "src") {print $(i+1); exit}}')"
HOST_NAME="$(hostname)"

if [[ -z "$LAN_IP" ]]; then
  echo "[FAIL] LAN IP를 찾지 못했습니다. Wi-Fi/Ethernet 연결을 확인하세요."
  exit 1
fi

CA_KEY="$TLS_DIR/webxr-local-ca.key"
CA_CERT="$TLS_DIR/webxr-local-ca.crt"
SERVER_KEY="$TLS_DIR/server.key"
SERVER_CSR="$TLS_DIR/server.csr"
SERVER_CERT="$TLS_DIR/server.crt"

if [[ ! -f "$CA_KEY" || ! -f "$CA_CERT" ]]; then
  openssl genrsa -out "$CA_KEY" 3072
  openssl req -x509 -new -sha256 -days 3650 \
    -key "$CA_KEY" \
    -out "$CA_CERT" \
    -subj "/CN=pi0 WebXR Local CA/O=pi0_sehwan"
  echo "[OK] WebXR 로컬 CA를 새로 만들었습니다."
else
  echo "[OK] 기존 WebXR 로컬 CA를 재사용합니다."
fi

openssl genrsa -out "$SERVER_KEY" 2048
openssl req -new -sha256 \
  -key "$SERVER_KEY" \
  -out "$SERVER_CSR" \
  -subj "/CN=$LAN_IP/O=pi0_sehwan WebXR"

openssl x509 -req -sha256 -days 825 \
  -in "$SERVER_CSR" \
  -CA "$CA_CERT" \
  -CAkey "$CA_KEY" \
  -CAcreateserial \
  -out "$SERVER_CERT" \
  -extfile <(printf '%s\n' \
    'basicConstraints=CA:FALSE' \
    'keyUsage=digitalSignature,keyEncipherment' \
    'extendedKeyUsage=serverAuth' \
    "subjectAltName=IP:$LAN_IP,IP:127.0.0.1,DNS:localhost,DNS:$HOST_NAME,DNS:$HOST_NAME.local")

chmod 600 "$CA_KEY" "$SERVER_KEY"
chmod 644 "$CA_CERT" "$SERVER_CERT"

echo "============================================================"
echo "[완료] WebXR HTTPS 인증서 생성"
echo "서버 IP: $LAN_IP"
echo "휴대폰에 설치할 CA 인증서: $CA_CERT"
echo "주의: webxr-local-ca.key와 server.key는 휴대폰으로 복사하지 마세요."
echo "CA SHA-256 지문:"
openssl x509 -in "$CA_CERT" -noout -fingerprint -sha256
echo "============================================================"
