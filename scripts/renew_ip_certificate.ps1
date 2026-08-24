$ErrorActionPreference = "Stop"

$sshKey = "C:\Users\we\Downloads\quantforge2.pem"
$server = "root@8.134.107.95"
$remoteCommand = @'
set -e
cd /opt/quantforge
export HTTPS_PROXY=http://127.0.0.1:17890
export HTTP_PROXY=http://127.0.0.1:17890
/opt/certbot-venv/bin/certbot renew --cert-name 8.134.107.95 --quiet --no-random-sleep-on-renew \
  --pre-hook "/bin/sh -c 'cd /opt/quantforge && docker compose -f compose.platform.yaml -f compose.production.yaml stop frontend'" \
  --post-hook "/bin/sh -c 'cd /opt/quantforge && docker compose -f compose.platform.yaml -f compose.production.yaml start frontend'" \
  --deploy-hook "/bin/sh -c 'cd /opt/quantforge && docker compose -f compose.platform.yaml -f compose.production.yaml restart frontend'"
'@
$remoteCommandBase64 = [Convert]::ToBase64String(
  [Text.Encoding]::UTF8.GetBytes($remoteCommand)
)
$remoteShellCommand = "echo '$remoteCommandBase64' | base64 -d | bash"

& ssh -o BatchMode=yes -o ConnectTimeout=20 `
  -R "127.0.0.1:17890:127.0.0.1:7890" `
  -i $sshKey $server $remoteShellCommand

if ($LASTEXITCODE -ne 0) {
  throw "QuantForge IP certificate renewal failed with exit code $LASTEXITCODE"
}
