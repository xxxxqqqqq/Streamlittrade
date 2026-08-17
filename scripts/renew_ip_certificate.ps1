$ErrorActionPreference = "Stop"

$sshKey = "C:\Users\we\Downloads\quantforge2.pem"
$server = "root@8.134.107.95"
$remoteCommand = @'
set -e
cd /opt/quantforge
export HTTPS_PROXY=http://127.0.0.1:17890
export HTTP_PROXY=http://127.0.0.1:17890
/opt/certbot-venv/bin/certbot renew --cert-name 8.134.107.95 --quiet \
  --pre-hook "cd /opt/quantforge && docker compose -f compose.platform.yaml -f compose.production.yaml stop frontend" \
  --post-hook "cd /opt/quantforge && docker compose -f compose.platform.yaml -f compose.production.yaml start frontend" \
  --deploy-hook "cd /opt/quantforge && docker compose -f compose.platform.yaml -f compose.production.yaml restart frontend"
'@

& ssh -o BatchMode=yes -o ConnectTimeout=20 `
  -R "127.0.0.1:17890:127.0.0.1:7890" `
  -i $sshKey $server $remoteCommand

if ($LASTEXITCODE -ne 0) {
  throw "QuantForge IP certificate renewal failed with exit code $LASTEXITCODE"
}
