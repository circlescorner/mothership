#!/bin/bash
# Mothership Gate Droplet Setup Script
# Run this on the Gate droplet via SSH to provision Caddy reverse proxy to Mothership Control Plane.
# Example: DEVPLANE_CONTROL_IP=10.116.0.3 bash setup-gate-droplet.sh

set -euo pipefail

DEVPLANE_CONTROL_IP="${DEVPLANE_CONTROL_IP:-10.116.0.3}"
export DEBIAN_FRONTEND=noninteractive
export APT_LISTCHANGES_FRONTEND=none

echo "=== Mothership Gate Droplet Setup ==="
echo "Using control droplet IP: $DEVPLANE_CONTROL_IP"

timeout 300 apt-get update -q || true
apt-get install -y curl wget debian-keyring debian-archive-keyring apt-transport-https

if ! command -v caddy &> /dev/null; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
    timeout 300 apt-get update -q || true
    apt-get install -y caddy
fi

mkdir -p /etc/ssl/certs /etc/ssl/private /var/log/caddy
chmod 700 /etc/ssl/private
chown root:root /etc/ssl/private

CERT_FILE="/etc/ssl/certs/cloudflare-origin.crt"
KEY_FILE="/etc/ssl/private/cloudflare-origin.key"

if [[ ! -f "$CERT_FILE" || ! -f "$KEY_FILE" ]]; then
    # Generate Cloudflare Origin CA certificate
    cat > "$CERT_FILE" << 'CERTEOF'
-----BEGIN CERTIFICATE-----
MIIEojCCA4qgAwIBAgIUPeTR/KjzCYrrF9Zjv6E21WGAI+4wDQYJKoZIhvcNAQEL
BQAwgYsxCzAJBgNVBAYTAlVTMRkwFwYDVQQKExBDbG91ZEZsYXJlLCBJbmMuMTQw
MgYDVQQLEytDbG91ZEZsYXJlIE9yaWdpbiBTU0wgQ2VydGlmaWNhdGUgQXV0aG9y
aXR5MRYwFAYDVQQHEw1TYW4gRnJhbmNpc2NvMRMwEQYDVQQIEwpDYWxpZm9ybmlh
MB4XDTI2MDIxNzIzMDcwMFoXDTQxMDIxMzIzMDcwMFowYjEZMBcGA1UEChMQQ2xv
dWRGbGFyZSwgSW5jLjEdMBsGA1UECxMUQ2xvdWRGbGFyZSBPcmlnaW4gQ0ExJjAk
BgNVBAMTHUNsb3VkRmxhcmUgT3JpZ2luIENlcnRpZmljYXRlMIIBIjANBgkqhkiG
9w0BAQEFAAOCAQ8AMIIBCgKCAQEA7oNyK1wgaG0mFjIw0PwyGgpsaF+fhTluUUj9
4ZJ9TWVWQla7HqjtDma+BZyYI7vahoTmqYacBR2hRgvkCVYQ17vAJm1J/ljECCgV
gpZoMngZhi0JKx6nyhk68FkqldOjP9t7MC6223QfMa4SG9pbh5JFWk421lJAl7fV
Yiyi9/JXfK4xa4whxZ60i+cr91T+GA46vkhommQUPPS9+n0AvwuY6xlyqDiy2IF3
vtzCenidNHjhboOBaLNgJM3JO6ZTcGg65pOU30NqwG2EcL3mZ+YlAxX14j+JVd3U
KrZALcFkMv3KI4ygEj/K2D7nF+lra/dFgWDe+A52sTcXR7s4qwIDAQABo4IBJDCC
ASAwDgYDVR0PAQH/BAQDAgWgMB0GA1UdJQQWMBQGCCsGAQUFBwMCBggrBgEFBQcD
ATAMBgNVHRMBAf8EAjAAMB0GA1UdDgQWBBTLTS41Zh4NiAJUQ0xi8OjinIbxDDAf
BgNVHSMEGDAWgBQk6FNXXXw0QIep65TbuuEWePwppDBABggrBgEFBQcBAQQ0MDIw
MAYIKwYBBQUHMAGGJGh0dHA6Ly9vY3NwLmNsb3VkZmxhcmUuY29tL29yaWdpbl9j
YTAlBgNVHREEHjAcgg0qLmdsb25kb3IueHl6ggtnbG9uZG9yLnh5ejA4BgNVHR8E
MTAvMC2gK6AphidodHRwOi8vY3JsLmNsb3VkZmxhcmUuY29tL29yaWdpbl9jYS5j
cmwwDQYJKoZIhvcNAQELBQADggEBAHsVxbwOMaXqoXtpB9I/byb3WZxXEfiZ6d/3
2FLLWTRmHshNovquLcrmfnD0VRXagO6XTJXaaI18BoNkj+kV/80+wrQE+bgqjyTR
8XHICoFzG0cVUMwWxH8ssVcWGsOEQuI7rLaDz7WgVTf34xMo5AddygjcN5Ii/YTg
qeLvqo2k0Sn8TLU5URl5AnkoYNElBw8UB/AybGqWND6c2D+ZseMYTkQkn80ocl/u
WHX140ZbjMf2zzFAZfFRXK1nljPJmmVQ7HBXG0jyph0mzsKd9Bw7Wu9fhmJnAuL4
45i+IYhwccrlYJThcFcEMTaIUCrRABGfmwtMlx3H57LqfXfNmZQ=
-----END CERTIFICATE-----
CERTEOF

    cat > "$KEY_FILE" << 'KEYEOF'
-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQDtmjH6u041eIAV
5DSqgQ1QIc5dGfb7zvIw+GiX78LvkkaQcwQz+/UN8dpCSyZP1AxgqrAl/ccrLO+L
VTRBozUbluhTbx2fRtnd59brZNLOd+ixJmmL+nY5gq9gqLNiThuC1e18FJi26/+e
lAft6Ru/zHcmHzFEaaHvcFpiAL8QQCsq21T2HXEzFq6ICC2d45pMZXzs6OVu/qPD
oCq7cfoQxmSerH2dCqMlow0ebtJwEZTpAnim/MUMlhVs1Gs+HJMvcjeE4vyOXVAV
/ylk2rNpcKi3veKo0yxUB6p22XK5e90+AMKe5GnLc/hB5fLRlE3uipz19LSSJzwL
7B7Q+tsHAgMBAAECggEAL+ikBEEJS4nRFdjub6TW6N3wLOCj5vE673nfKSesoD7X
4J94bPz0VAv8rNpXTshceI9iNj7eDowgfvE+uK9ucXIzxUMF74xLOM3bDZrGUOBn
uHSc2p81gHIj57MMfJlwPajiGl9Szat3XuPNV4Dl2f4h1jt65ScBgnSenN02qVFL
hbs1onDyelVm5OQGeeD4DhJNm98oYqPpqK0by4ZDoj5IVODdte7Wtud1j7iEa1ty
pMKnpdAKlIrqEoGjC2X21A+GWTwWGhEI8gRH8dNR479DLicH/B7rWJnjZlMccWGK
VI4ZvOTrk5kQxCoI/cyMzvI+DRX07OnczSFwV1jL0QKBgQD8vFVs4fUXtdeEKRXG
U/e+Nx3tf2RL9J9RWaBQD4wvSYZ/0Pr5FrswQXEDl0oSWLsEzjnPqOCQh+4s8qIX
rxTNyxdTlFuxWQB6gZQuLcYWmu1tk8842b7zusT+BVmRq2PHRoULjW19fJOLUCnf
dc7fzuP615KB7ahDPOHgyoV9MQKBgQDwq9LHpV+clL0I8oeEdMZTkqmBQ1QuqT0d
G8R3xX9YrtKBLS1saNpvYVbncC94bKhsDE6B8pliN3cz+V/BGclvZXPTI3Dr6VAH
W1d2z4dN3xo0HBeJdpsdEdnHw62aZLghAd5MAVzgifNp1JyaCljdHBNfP2J/dSm6
YWfNlyjttwKBgHws7Kv6uTlVFvbQWOqBBxBmdEXkeZr4Le8CYknz2aTCM1tJioYo
LQCgpq5k/vfUsM7DpJPrHarlnphm/k00sLwMNQHTutmAKUQHto6Z3uHsbQuRvBbq
pW+LLI7CgieYVgXrGCN88XbeZn/key5X67T7KfhtQoakBjBDEZgo6T2BAoGBAO1e
qq+aXejTknZGrn5npkw7NM93FopHBS22e1oeAnH3S0t4wXpRGFAOU2ZE8az2jk6y
/KOSINIMHpe2d0i/JDuodkpihDdJkFMRNfzKxop5ZyDKLDS6NFbBimhKiOjkOe7k
JtoT5gTYSqmwtxv+5JJ/5GNm4sEPT66x722IjyeVAoGBAJ+CLSKrKvhGMNwdoNrn
RIbRvpntzNehItwULKBNCeRVOFCxI4Lu48uX3kMeIOeLjelcBcVUIvNGs6wiH2hH
8L9oVUa6mHCacsJzXA55MXjPLM7QomJeHPKJc0DeQdLza/DtKbDzd6kF5r+yHL1Q
jfglMgWpxuhEsg4GyHuR7tBn
-----END PRIVATE KEY-----
KEYEOF
    chmod 644 "$CERT_FILE"
    chmod 600 "$KEY_FILE"
fi

cat > /etc/caddy/Caddyfile << CADDYEOF
{
    auto_https off
    admin off
}

# Proxy to Mothership Control Plane over port 8000
cp.glondor.xyz, glondor.xyz, www.glondor.xyz {
    tls /etc/ssl/certs/cloudflare-origin.crt /etc/ssl/private/cloudflare-origin.key
    
    reverse_proxy ${DEVPLANE_CONTROL_IP}:8000 {
        header_up Host {host}
        header_up X-Real-IP {remote}
        header_up X-Forwarded-For {remote}
        header_up X-Forwarded-Proto {scheme}
        header_up CF-Connecting-IP {http.request.header.CF-Connecting-IP}
        header_up CF-IPCountry {http.request.header.CF-IPCountry}
        header_up CF-Ray {http.request.header.CF-Ray}
    }
    
    header {
        X-Frame-Options "SAMEORIGIN"
        X-XSS-Protection "1; mode=block"
        X-Content-Type-Options "nosniff"
        Referrer-Policy "strict-origin-when-cross-origin"
        -Server
    }
}
CADDYEOF

systemctl enable caddy
systemctl restart caddy

echo "✓ Gate droplet configured to proxy to Mothership at ${DEVPLANE_CONTROL_IP}:8000"
