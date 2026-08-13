# Forgejo Migration Guide for Kenya Vehicle Collateral Risk Engine

## Why Forgejo?

For a Kenyan fintech handling bank data (Family Bank, Equity, KCB):
- **CLOUD Act risk**: GitHub is under US jurisdiction. Any US agency can request data.
- **ODPC compliance**: Kenya's Data Protection Act requires data residency in Kenya.
- **Self-hosted**: Forgejo runs on your infrastructure. Your code never leaves Kenya.

## Quick Setup (30 minutes)

### 1. Start Forgejo

```bash
docker compose up -d forgejo
```

Wait 30 seconds, then open `http://localhost:3000`.

### 2. Initial Configuration

1. **Database**: SQLite (default, fine for small teams)
2. **Server Domain**: `git.riskengine.co.ke`
3. **Create admin user**: `admin` / (set strong password)

### 3. Create Organization and Repository

```
Organization: risk-engine
Repository:   kenya-vehicle-collateral
```

### 4. Migrate from GitHub

```bash
# Add Forgejo as a remote (keeps GitHub as backup)
git remote add forgejo https://localhost:3000/risk-engine/kenya-vehicle-collateral.git

# Push all branches
git push forgejo --all

# Push all tags
git push forgejo --tags
```

### 5. Update CI/CD

Replace GitHub Actions with Forgejo Actions (compatible syntax):

```yaml
# .forgejo/workflows/ci.yml
on: [push]
jobs:
  test:
    runs-on: docker
    steps:
      - uses: actions/checkout@v4
      - run: npm ci && npm test
```

### 6. Set Forgejo as Primary

```bash
# Make Forgejo the default remote
git remote set-url origin https://git.riskengine.co.ke/risk-engine/kenya-vehicle-collateral.git

# Keep GitHub as mirror (optional)
git remote rename origin github
git remote add origin https://git.riskengine.co.ke/risk-engine/kenya-vehicle-collateral.git
```

## Production Deployment

For production with HTTPS and a real domain:

```nginx
# nginx.conf
server {
    listen 443 ssl;
    server_name git.riskengine.co.ke;

    ssl_certificate /etc/letsencrypt/live/git.riskengine.co.ke/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/git.riskengine.co.ke/privkey.pem;

    location / {
        proxy_pass http://forgejo:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## ODPC Registration

Register with Kenya's Office of the Data Protection Commissioner:

1. Visit https://odpc.go.ke/registration
2. Organization: (your company name)
3. Data types: Vehicle registration data, Financial data
4. Processing purpose: Fraud detection in vehicle-secured lending
5. Data residency: Kenya (self-hosted Forgejo + Neo4j on KE servers)
6. Retention period: 7 years (CBK requirement)

## Security Checklist

- [ ] Forgejo behind HTTPS (Let's Encrypt or org cert)
- [ ] SSH key auth for all developers
- [ ] 2FA enabled for admin accounts
- [ ] Webhooks only over HTTPS
- [ ] No personal access tokens in code
- [ ] Repository access restricted to team members
- [ ] Audit logs enabled
- [ ] Backup cron job (daily, encrypted, offsite)
