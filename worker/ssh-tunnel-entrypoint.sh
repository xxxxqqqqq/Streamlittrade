#!/bin/sh
set -eu

install -m 0600 /run/secrets/worker_ssh_key /tmp/worker_ssh_key

exec ssh -NT \
  -i /tmp/worker_ssh_key \
  -o BatchMode=yes \
  -o ConnectTimeout=15 \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o StrictHostKeyChecking=accept-new \
  -L "0.0.0.0:${LOCAL_POSTGRES_PORT}:127.0.0.1:${REMOTE_POSTGRES_PORT}" \
  -L "0.0.0.0:${LOCAL_REDIS_PORT}:127.0.0.1:${REMOTE_REDIS_PORT}" \
  -L "0.0.0.0:${LOCAL_MINIO_PORT}:127.0.0.1:${REMOTE_MINIO_PORT}" \
  "${SSH_USER}@${SSH_HOST}"
