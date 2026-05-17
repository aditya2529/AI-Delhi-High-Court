# nginx — Delhi HC Case Tracker reverse-proxy configs

| File | Purpose |
|---|---|
| `private-alpha.conf` | The GREEN-ZONE default. HTTP basic auth on every path, TLS-only, `noindex, nofollow, noarchive` header on every response, frame-ancestors locked to `'none'`. Use this for **any** non-localhost deploy until Phase-0 gates G2 (ToS) + G3 (DPDPA counsel sign-off) close. |

## One-time setup on the host

```bash
# 1. Create the htpasswd file with the first tester credential.
sudo htpasswd -cB /etc/nginx/dhc.htpasswd alpha-tester
# (prompts for password; bcrypt hash; stored as one user per line)

# 2. Add additional testers (no -c, that would wipe the file).
sudo htpasswd -B /etc/nginx/dhc.htpasswd second-tester

# 3. Lock down file permissions.
sudo chown root:nginx /etc/nginx/dhc.htpasswd
sudo chmod 0640      /etc/nginx/dhc.htpasswd

# 4. Drop the conf in place + reload.
sudo cp infrastructure/nginx/private-alpha.conf /etc/nginx/conf.d/
sudo nginx -t && sudo systemctl reload nginx
```

## Smoke test the auth wall

```bash
# Without credentials — must return 401.
curl -sI https://alpha.example.invalid/ | head -1
#   HTTP/2 401

# With credentials — must reach the Next.js app.
curl -sI -u alpha-tester:<password> https://alpha.example.invalid/ | head -1
#   HTTP/2 200

# Health endpoint — open by design (uptime monitor).
curl -sI https://alpha.example.invalid/api/v1/health | head -1
#   HTTP/2 200
```

## When you accidentally deploy without auth

If a deploy ever lands without the htpasswd in place, `auth_basic_user_file`
will point at a non-existent path and nginx will reject *every* request with
a 500. That's the intended failure mode — fail closed, not open.
