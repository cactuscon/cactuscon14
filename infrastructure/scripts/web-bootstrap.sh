#!/usr/bin/env bash
# Bootstrap script for Ubuntu 24.04 EC2 instance.
#
# Provisions:
# - nginx
# - HTTP site for badge-ota.cactuscon.com serving /srv/www/ota
# - HTTP reverse proxy site for badge.cactuscon.com (FastAPI upstream)
# - Optional certbot automation (when DNS is ready)
#
# Safety:
# - Designed to be re-runnable (idempotent symlinks, mkdir -p, etc.)
#
# Optional environment variables:
# - PORTABLE_UPSTREAM (default: http://10.14.0.102:8000)
# - ENABLE_BADGE_SITE=1 (enable badge.cactuscon.com in nginx)
# - CERTBOT_EMAIL=you@example.com (required for non-interactive certbot)
# - RUN_CERTBOT_BADGE=1 (issue cert for badge.cactuscon.com)
# - RUN_CERTBOT_OTA=1 (issue cert for badge-ota.cactuscon.com)

set -euo pipefail

BADGE_UPSTREAM="${PORTABLE_UPSTREAM:-http://10.14.0.102:8000}"

apt-get update
apt-get install -y nginx certbot python3-certbot-nginx

# -----------------------------------------------------------------------------
# OTA web root
# -----------------------------------------------------------------------------

mkdir -p /srv/www/ota
chown -R www-data:www-data /srv/www/ota

# Create a 1995-style fake Radioshack static index.html for OTA.
# This is optional and safe to overwrite.
cat <<'EOF' > /srv/www/ota/index.html
<!DOCTYPE html>
<html>
<head>
	<title>RadioShack - Welcome to the Shack!</title>
	<style>
		body {
			background: #222;
			color: #000;
			font-family: 'Courier New', Courier, monospace;
			margin: 0;
			padding: 0;
		}
		.container {
			width: 760px;
			margin: 30px auto;
			background: #fff;
			border: 4px solid #d52b1e;
			box-shadow: 0 0 10px #888;
			padding: 20px;
		}
		h1 {
			color: #d52b1e;
			font-size: 2.5em;
			text-align: center;
			font-family: Impact, Charcoal, sans-serif;
			margin-bottom: 0.2em;
			letter-spacing: 2px;
			text-shadow: 2px 2px 0 #fff, 4px 4px 0 #222;
		}
		h2 {
			color: #222;
			font-size: 1.5em;
			border-bottom: 2px dotted #d52b1e;
		}
		.nav {
			background: #d52b1e;
			color: #fff;
			padding: 8px;
			text-align: center;
			margin-bottom: 20px;
			border-bottom: 2px solid #222;
		}
		.nav a {
			color: #fff;
			text-decoration: underline;
			margin: 0 10px;
			font-weight: bold;
		}
		.product {
			border: 2px solid #d52b1e;
			background: #f4f4f4;
			margin: 10px 0;
			padding: 10px;
			display: flex;
			align-items: center;
		}
		.product img {
			width: 80px;
			height: 80px;
			margin-right: 20px;
			border: 2px solid #222;
			background: #fff;
		}
		.footer {
			text-align: center;
			color: #d52b1e;
			font-size: 0.9em;
			margin-top: 30px;
		}
		hr {
			border: none;
			border-top: 2px solid #d52b1e;
			margin: 20px 0;
		}
	</style>
</head>
<body>
	<div class="container">
		<h1>RadioShack&reg;</h1>
		<div class="nav">
			<a href="#">Home</a> |
			<a href="#">Weekly Ad</a> |
			<a href="#">Store Locator</a> |
			<a href="#">Contact Us</a>
		</div>
		<h2>Welcome to the Shack! <span style="font-size:0.7em; color:#d52b1e;">(1995 Edition)</span></h2>
		<p>Browse our latest selection of electronics, gadgets, and more! Order by phone: <b style="color:#d52b1e;">1-800-THE-SHACK</b></p>
		<div class="product">
			<img src="https://upload.wikimedia.org/wikipedia/commons/6/6e/RadioShack_TRS-80_Model_100.jpg" alt="TRS-80 Model 100">
			<div>
				<b>TRS-80 Model 100 Portable Computer</b><br>
				<span>Now only $799.99!<br>Perfect for business on the go.</span>
			</div>
		</div>
		<div class="product">
			<img src="https://upload.wikimedia.org/wikipedia/commons/2/2e/RadioShack_Realistic_Pro-2006_Scanner.jpg" alt="Realistic Pro-2006 Scanner">
			<div>
				<b>Realistic Pro-2006 Scanner</b><br>
				<span>Scan the airwaves!<br>Special price: $199.99</span>
			</div>
		</div>
		<div class="product">
			<img src="https://upload.wikimedia.org/wikipedia/commons/3/3e/RadioShack_Archer_Space_Patrol_Walkie_Talkie.jpg" alt="Archer Walkie Talkie">
			<div>
				<b>Archer Space Patrol Walkie Talkie</b><br>
				<span>2-mile range!<br>Only $29.99 per pair</span>
			</div>
		</div>
		<div class="footer">
			<hr>
			<span>&copy; 1995 RadioShack&reg;. All rights reserved. | <a href="#" style="color:#d52b1e;">Privacy Policy</a></span>
		</div>
	</div>
</body>
</html>
EOF

# -----------------------------------------------------------------------------
# nginx sites
# -----------------------------------------------------------------------------

# badge.cactuscon.com reverse proxy (leave disabled by default).
cat <<EOF > /etc/nginx/sites-available/badge.cactuscon.com
server {
	listen 80;
	server_name badge.cactuscon.com;

	location / {
		proxy_pass ${BADGE_UPSTREAM};
		proxy_set_header Host \$host;
		proxy_set_header X-Real-IP \$remote_addr;
		proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
		proxy_set_header X-Forwarded-Proto \$scheme;
	}
}
EOF

# badge-ota.cactuscon.com static OTA host.
cat <<'EOF' > /etc/nginx/sites-available/badge-ota.cactuscon.com
server {
	listen 80;
	server_name badge-ota.cactuscon.com;
	root /srv/www/ota;
	index index.html;

	location /ota {
		try_files $uri $uri/ =404;
	}
}
EOF

ln -sf /etc/nginx/sites-available/badge-ota.cactuscon.com /etc/nginx/sites-enabled/badge-ota.cactuscon.com

if [[ "${ENABLE_BADGE_SITE:-0}" == "1" ]]; then
  ln -sf /etc/nginx/sites-available/badge.cactuscon.com /etc/nginx/sites-enabled/badge.cactuscon.com
else
  rm -f /etc/nginx/sites-enabled/badge.cactuscon.com || true
fi

nginx -t
systemctl reload nginx

# -----------------------------------------------------------------------------
# certbot (optional)
# -----------------------------------------------------------------------------
#
# These are intentionally opt-in because they require:
# - DNS records already pointing at this host
# - port 80 reachable from the Internet for HTTP-01 validation
#
# To run non-interactively:
#   export CERTBOT_EMAIL=you@example.com
#   export RUN_CERTBOT_BADGE=1
#   export RUN_CERTBOT_OTA=1
#
# Note: certbot will modify nginx configs to add HTTPS server blocks.

if [[ "${RUN_CERTBOT_BADGE:-0}" == "1" || "${RUN_CERTBOT_OTA:-0}" == "1" ]]; then
  if [[ -z "${CERTBOT_EMAIL:-}" ]]; then
    echo "Error: CERTBOT_EMAIL is required for non-interactive certbot runs."
    echo "Set CERTBOT_EMAIL and rerun with RUN_CERTBOT_BADGE=1 and/or RUN_CERTBOT_OTA=1."
    exit 1
  fi
fi

if [[ "${RUN_CERTBOT_BADGE:-0}" == "1" ]]; then
  if [[ "${ENABLE_BADGE_SITE:-0}" != "1" ]]; then
    echo "Error: badge.cactuscon.com site must be enabled for certbot --nginx."
    echo "Set ENABLE_BADGE_SITE=1 and rerun."
    exit 1
  fi
  certbot --nginx -n --agree-tos -m "${CERTBOT_EMAIL}" -d badge.cactuscon.com
fi

if [[ "${RUN_CERTBOT_OTA:-0}" == "1" ]]; then
  certbot --nginx -n --agree-tos -m "${CERTBOT_EMAIL}" -d badge-ota.cactuscon.com
fi

echo "Bootstrap complete."
