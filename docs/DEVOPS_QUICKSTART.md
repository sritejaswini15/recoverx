# RecoverX Quick Start - DevOps Deployment Guide

## 30-Minute Deploy to Production

### Prerequisites
- GitHub repo with this code
- Render.com account
- Razorpay account (test or production)
- 1 password manager (for storing secrets)

### Step 1: Generate Secrets (2 min)

```bash
# Generate random AUTH_SECRET
python3 -c "import secrets; print('AUTH_SECRET=' + secrets.token_hex(32))"

# Generate random ADMIN_PASSWORD
openssl rand -base64 24

# Get from Razorpay Dashboard
# Settings → Webhooks → Create Webhook
# Use the secret it generates
```

Save these values securely (password manager, not git).

### Step 2: Push to GitHub (3 min)

```bash
cd /path/to/recoverx
git push origin main
```

If git index is corrupted:
```bash
rm -f .git/index
git reset
git add .
git commit -m "Fix: Production deployment"
git push origin main
```

### Step 3: Create Render Project (5 min)

1. Go to https://dashboard.render.com
2. Click "New" → "Project from GitHub"
3. Select recoverx repository
4. Click "Deploy"
5. Render will detect render.yaml and create all services

### Step 4: Configure Environment Variables (10 min)

Go to Render Dashboard → recoverx-api → Environment

Add these variables (copy values from Step 1):

```
AUTH_SECRET=<generated value>
BOOTSTRAP_ADMIN_EMAIL=your-admin@company.com
BOOTSTRAP_ADMIN_PASSWORD=<generated value>
RAZORPAY_WEBHOOK_SECRET=<from Razorpay Dashboard>
BOOTSTRAP_RAZORPAY_ACCOUNT_ID=acct_XXXXXXXXXXXX
RAZORPAY_KEY_ID=rzp_live_XXXXXXXXXXXX
RAZORPAY_KEY_SECRET=<if using live Razorpay>
```

**Important**: Mark all secrets with checkmark (they'll use `sync: false`)

### Step 5: Configure Frontend (2 min)

Go to Render Dashboard → recoverx-frontend → Environment

Add:
```
NEXT_PUBLIC_API_URL=https://recoverx-api-XXXXX.onrender.com
```

(Get full URL from recoverx-api Settings)

### Step 6: Update CORS Settings (2 min)

Go to recoverx-api → Environment, update:
```
CORS_ORIGINS=https://recoverx-frontend-XXXXX.onrender.com
```

### Step 7: Configure Razorpay Webhooks (3 min)

Go to Razorpay Dashboard → Settings → Webhooks

Create webhook:
- **URL**: `https://recoverx-api-XXXXX.onrender.com/webhooks/razorpay`
- **Events**: Select all payment events
- **Secret**: Use your RAZORPAY_WEBHOOK_SECRET
- **Active**: Yes

### Step 8: Verify Deployment (3 min)

```bash
# Wait for Render deployment to finish (shows "Live")
# Then test:

curl https://recoverx-api-XXXXX.onrender.com/health
# Should return: {"status": "ok", ...}

curl https://recoverx-frontend-XXXXX.onrender.com
# Should show login page
```

### Step 9: Test Login (2 min)

1. Open https://recoverx-frontend-XXXXX.onrender.com
2. Login with:
   - Email: your-admin@company.com
   - Password: <value from Step 1>
3. Should see dashboard with 500 demo cases

### Step 10: Run E2E Tests (1 min)

```bash
export PLAYWRIGHT_TEST_BASE_URL="https://recoverx-frontend-XXXXX.onrender.com"
export RECOVERX_E2E_API_URL="https://recoverx-api-XXXXX.onrender.com"
export RECOVERX_E2E_EMAIL="your-admin@company.com"
export RECOVERX_E2E_PASSWORD="<value from Step 1>"
export SKIP_WEBSERVER_START="true"

cd frontend
npm run test:e2e
```

Should pass all 10 tests.

---

## Ongoing Operations

### Daily Monitoring

```bash
# Check health
curl https://recoverx-api-XXXXX.onrender.com/health

# View logs (Render Dashboard)
# recoverx-api → Logs
# recoverx-frontend → Logs
# recoverx-postgres → Monitoring
```

### Database Backup & Restore

```bash
# Render auto-backups daily (7-day retention)
# Render Dashboard → recoverx-postgres → Backups

# Manual backup via CLI (if installed):
render database backup recoverx-postgres
```

### Scaling

If seeing high CPU/memory:

```bash
# In render.yaml:
# - type: web
#   name: recoverx-api
#   numInstances: 2  # was 1, now 2
# Then redeploy
```

### Logs & Debugging

```bash
# Real-time logs
render service logs recoverx-api --tail 100

# Specific error search
render service logs recoverx-api | grep "ERROR"
```

### Emergency Commands

```bash
# View active database connections
psql $DATABASE_URL -c "SELECT count(*) FROM pg_stat_activity;"

# Check Redis
redis-cli -u $REDIS_URL PING

# Clear payment link cache (if needed)
redis-cli -u $REDIS_URL FLUSHDB
```

---

## Troubleshooting

### "Production configuration is incomplete"

**Fix**: Verify all required env vars in Render:
```
- AUTH_SECRET (not empty, not "recoverx-local-development-secret")
- RAZORPAY_WEBHOOK_SECRET (not empty)
- BOOTSTRAP_ADMIN_EMAIL (not empty)
- BOOTSTRAP_ADMIN_PASSWORD (16+ chars)
```

### "alembic upgrade head failed"

**Fix**: Check PostgreSQL is ready:
```bash
# SSH into container (Render Shell):
render shell recoverx-api

# Then inside:
psql $DATABASE_URL -c "SELECT 1;"

# Run migration manually:
alembic upgrade head
```

### "Invalid webhook signature"

**Fix**: Verify secrets match:
```bash
# 1. Razorpay Dashboard → Webhooks → check secret
# 2. Render Dashboard → recoverx-api → Environment → RAZORPAY_WEBHOOK_SECRET
# Must be identical
```

### "Tests fail on deployed instance"

**Fix**: Verify environment variables:
```bash
echo "Base URL: $PLAYWRIGHT_TEST_BASE_URL"
echo "API URL: $RECOVERX_E2E_API_URL"
echo "Email: $RECOVERX_E2E_EMAIL"

# Then test manually:
curl -X POST $RECOVERX_E2E_API_URL/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "your-admin@company.com", "password": "your_password"}'
```

---

## Adding New Team Members

```bash
# SSH into API
render shell recoverx-api

# Create new admin user
python -c "
from app.db import User, Organization, get_session, hash_password
from sqlalchemy import select

session = next(get_session())
admin = session.scalar(select(User).where(User.email == 'admin@company.com'))
org = admin.organization

new_user = User(
    id='user_' + os.urandom(8).hex(),
    email='newperson@company.com',
    password_hash=hash_password('temporary-password'),
    organization_id=org.id,
    role='OPERATOR',
)
session.add(new_user)
session.commit()
print('Created new_person@company.com with temporary-password')
print('They should reset password on first login')
"
```

---

## Going Live with Real Razorpay

### Step 1: Get Live Keys

Razorpay Dashboard → Settings → API Keys → Live Keys

### Step 2: Update Render Environment

```
RAZORPAY_KEY_ID=rzp_live_XXXXXXXXXXXX
RAZORPAY_KEY_SECRET=<from dashboard>
PAYMENT_PROVIDER=live
```

### Step 3: Reconfigure Webhook

Razorpay Dashboard → Webhooks → Create new webhook
- URL: https://recoverx-api-XXXXX.onrender.com/webhooks/razorpay
- Use LIVE credentials secret
- Active: Yes

### Step 4: Test with Real Payment

- Create recovery case
- Generate payment link
- Pay with real card
- Verify webhook triggers
- Check case updates to RECOVERED

---

## Disaster Recovery

### Database Corrupted

```bash
# 1. Render Dashboard → recoverx-postgres → Backups
# 2. Click "Restore" on recent backup
# 3. App will auto-reconnect (no restart needed)
```

### Deployment Failed

```bash
# Check logs
render service logs recoverx-api --tail 200

# Rollback to previous build
render service update recoverx-api --no-deploy  # pauses auto-updates
git revert <commit>
git push origin main  # redeploys previous version
```

### API Crashed

```bash
# Render auto-restarts, usually within 30 seconds
# Check status in Dashboard

# If stuck, manually restart:
render service restart recoverx-api
```

---

## Useful Links

- **Dashboard**: https://dashboard.render.com
- **Razorpay Dashboard**: https://dashboard.razorpay.com
- **API Docs**: GET https://recoverx-api-XXXXX.onrender.com/docs
- **Frontend**: https://recoverx-frontend-XXXXX.onrender.com
- **Logs**: Render Dashboard → [service] → Logs

---

## Performance Baseline

Expected performance on Render Starter:

| Metric | Expected |
|--------|----------|
| API response time | < 200ms (90th percentile) |
| Database queries | < 50ms median |
| Payment link creation | < 100ms |
| Webhook processing | < 500ms |
| Auth token validation | < 10ms |
| Dashboard load | < 2s first paint |

If performance degrades:
1. Check active database connections: `SELECT count(*) FROM pg_stat_activity;`
2. Check slow queries: Check Render PostgreSQL logs
3. Monitor Redis memory: `redis-cli -u $REDIS_URL INFO memory`
4. Scale up if needed: Render Dashboard → Update plan

---

## Getting Help

1. **Check logs first**: Render Dashboard → [service] → Logs
2. **Verify env vars**: Render Dashboard → Settings → Environment
3. **Test health endpoint**: `curl https://recoverx-api-XXXXX.onrender.com/health`
4. **Review docs**: Check docs/PRODUCTION_DEPLOYMENT.md for detailed guide
5. **Contact support**: Create GitHub issue with:
   - Error message
   - Service logs (last 50 lines)
   - Steps to reproduce
