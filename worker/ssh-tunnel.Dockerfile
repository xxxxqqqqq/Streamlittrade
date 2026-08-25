FROM alpine:3.22

RUN apk add --no-cache openssh-client

COPY worker/ssh-tunnel-entrypoint.sh /usr/local/bin/ssh-tunnel-entrypoint
RUN chmod 0755 /usr/local/bin/ssh-tunnel-entrypoint

ENTRYPOINT ["/usr/local/bin/ssh-tunnel-entrypoint"]
