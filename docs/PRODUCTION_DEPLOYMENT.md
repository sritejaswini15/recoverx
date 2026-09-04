# RecoverX Production Deployment & Readiness Guide

## Overview

RecoverX is now production-ready with the following critical fixes implemented:

- ✅ **Dockerfile** - Fixed to include alembic migrations
- ✅ **Render Blueprint** - Production-grade deployment with PostgreSQL, Redis, worker service
- ✅ **Authentication** - Session-based tokens with revocation, logout endpoint
- ✅ **Payment Links** - Tokenized, expiring, non-guessable payment links
- ✅ **Webhooks** - Merchant-mapped, signed, deduplicated
- ✅ **Database** - Migrations-only in production, no `create_all()`
- ✅ **Config Validation** - Production enforces all required secrets
- ✅ **E2E Tests** - Comprehensive test suite covering all critical paths
- ✅ **Bootstrap Admin** - Automatic admin creation on first startup

## Pre-Deployment Checklist

### 1. Security Configuration

```bash
# Generate production secrets
AUTH_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
ADMIN_PASSWORD=$(openssl rand -base64 24)
WEBHOOK_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")

echo "AUTH_SECRET=$AUTH_SECRET"
echo "BOOTSTRAP_ADMIN_PASSWORD=$ADMIN_PASSWORD"
echo "RAZORPAY_WEBHOOK_SECRET=$WEBHOOK_SECRET"
```

**Copy `.env.production.example` → `.env.production` and fill in:**
- `AUTH_SECRET` - Random 32+ char hex string
- `BOOTSTRAP_ADMIN_EMAIL` - Admin login email
- `BOOTSTRAP_ADMIN_PASSWORD` - Strong 16+ char password
- `RAZORPAY_WEBHOOK_SECRET` - Get from Razorpay Dashboard
- `RAZORPAY_KEY_ID` & `RAZORPAY_KEY_SECRET` - Leave blank for simulation
- `BOOTSTRAP_RAZORPAY_ACCOUNT_ID` - Get from Razorpay Dashboard

### 2. Git Repository

```bash
# Fix corrupted git index if needed
rm -f .git/index
git reset

# Verify no secrets are committed
git log -p --follow -- '.env*' '*.key' '*.secret'

# Add to .gitignore (already there, but verify)
echo ".env.production" >> .gitignore
git add .gitignore && git commit -m "Ensure .env.production never committed"
```

### 3. Local Docker Testing

```bash
# Build docker images
docker-compose build

# Start full stack
docker-compose up -d

# Run migrations
docker-compose exec backend alembic upgrade head

# Seed test data (dev only)
docker-compose exec backend python scripts/seed_synthetic_data.py

# Access UI at http://localhost:3000
# API at http://localhost:8000
# Login: admin@recoverx.local / recoverx-demo
```

### 4. Database Setup

```bash
# Create database backup strategy
# For Render: Dashboard → Database → Backups tab
# Render default: 7-day backups, automatic

# Test backup/restore locally
docker-compose exec postgres pg_dump recoverx > backup.sql
docker-compose exec postgres dropdb recoverx
docker-compose exec postgres createdb recoverx
cat backup.sql | docker-compose exec -T postgres psql recoverx
```

## Deployment Steps (Render)

### Step 1: Create Render Services

```bash
# Push code to GitHub
git push origin main

# Go to Render Dashboard: https://dashboard.render.com

# Create new project from render.yaml
# Settings → Deploy from GitHub → Select repository → Deploy
```

### Step 2: Configure Environment Variables

**In Render Dashboard for recoverx-api:**

1. Settings → Environment Variables
2. Add all variables from `.env.production.example`:
   - `AUTH_SECRET` (from step 1 above)
   - `BOOTSTRAP_ADMIN_EMAIL`
   - `BOOTSTRAP_ADMIN_PASSWORD`
   - `RAZORPAY_WEBHOOK_SECRET`
   - `BOOTSTRAP_RAZORPAY_ACCOUNT_ID`
   - `RAZORPAY_KEY_ID` (leave blank for simulation)
   - `RAZORPAY_KEY_SECRET` (leave blank for simulation)
   - `CORS_ORIGINS` (set to frontend URL once deployed)
   - `NEXT_PUBLIC_API_URL` (set to API URL)

3. Mark sensitive values with `sync: false` in render.yaml ✅ (already done)

### Step 3: Verify Database Migration

```bash
# After deployment, check logs
# Render Dashboard → recoverx-api → Logs

# Should see:
# - "alembic upgrade head" running
# - "Creating bootstrap admin..."
# - "Application startup complete" at http://0.0.0.0:8000
```

### Step 4: Configure Razorpay Webhooks

**In Razorpay Dashboard:**

1. Settings → Webhooks → Create Webhook
2. URL: `https://recoverx-api-xxxxx.onrender.com/webhooks/razorpay`
3. Events to subscribe:
   - `payment.captured`
   - `payment.failed`
   - `payment_link.paid`
   - `payment_link.expired`
4. Secret: Use `RAZORPAY_WEBHOOK_SECRET` from environment
5. Active: Yes

### Step 5: Test Deployment

```bash
# Get deployed API URL from Render
API_URL="https://recoverx-api-xxxxx.onrender.com"

# Test health check
curl $API_URL/health

# Should return: {"status": "ok", ...}

# Test login (optional, needs admin account created)
curl -X POST $API_URL/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@yourdomain.com", "password": "your_password"}'

# Frontend URL from Render
# Should auto-deploy with NEXT_PUBLIC_API_URL set
```

## Post-Deployment Operations

### Verify Everything Works

1. **Access Frontend**
   ```
   https://recoverx-frontend-xxxxx.onrender.com
   ```
   - Login with admin credentials
   - Should see 500 demo customers
   - Dashboard should show metrics

2. **Test Authentication**
   ```bash
   # Login
   curl -X POST https://recoverx-api-xxxxx.onrender.com/auth/login \
     -H "Content-Type: application/json" \
     -d '{
       "email": "admin@yourdomain.com",
       "password": "your_password"
     }'
   
   # Should return access_token
   # Store in $TOKEN
   
   # Use token
   curl https://recoverx-api-xxxxx.onrender.com/recovery-cases \
     -H "Authorization: Bearer $TOKEN"
   
   # Logout (revoke token)
   curl -X POST https://recoverx-api-xxxxx.onrender.com/auth/logout \
     -H "Authorization: Bearer $TOKEN"
   
   # Token should now be invalid
   curl https://recoverx-api-xxxxx.onrender.com/recovery-cases \
     -H "Authorization: Bearer $TOKEN"
   # Should return 401 Unauthorized
   ```

3. **Test Recovery Flow**
   - Navigate to Cases
   - Select a case
   - Click "Execute" to create payment link
   - Verify payment link is generated with expiry
   - Simulate payment via dashboard

4. **Test Webhooks**
   - Use Postman or curl to send test webhook
   - Verify deduplication works
   - Check audit logs for webhook events

### Run Deployed E2E Tests

```bash
# Set environment variables
export PLAYWRIGHT_TEST_BASE_URL="https://recoverx-frontend-xxxxx.onrender.com"
export RECOVERX_E2E_API_URL="https://recoverx-api-xxxxx.onrender.com"
export RECOVERX_E2E_EMAIL="admin@yourdomain.com"
export RECOVERX_E2E_PASSWORD="your_password"
export SKIP_WEBSERVER_START="true"

# Run comprehensive test suite
cd frontend
npm run test:e2e

# Should pass all 10 test scenarios:
# 1. Login and dashboard loads
# 2. Dashboard metrics are accurate
# 3. Case details show diagnosis
# 4. Execute recovery and process payment
# 5. Customer can access payment page
# 6. Logout revokes session
# 7. Role-based access control
# 8. Webhook deduplication
# 9. Case filtering and sorting
# 10. Analytics dashboard
```

## Monitoring & Maintenance

### Health Checks

Render auto-monitors health endpoint: `/health`

```bash
# Manual health check
curl https://recoverx-api-xxxxx.onrender.com/health

# Expected response
{
  "status": "ok",
  "service": "recoverx-control-plane",
  "mode": "simulation",
  "timestamp": "2026-09-04T12:34:56+00:00"
}
```

### Database Maintenance

1. **Automatic Backups** (Render):
   - Default: 7-day retention
   - Manual backups via Dashboard

2. **Cleanup Cron Job** (if enabled in render.yaml):
   - Daily at 2 AM UTC
   - Marks expired payment links as EXPIRED
   - Cleans up revoked sessions older than 30 days

3. **Scale Database**:
   - Monitor PostgreSQL CPU/memory in Render
   - Upgrade to higher plan if needed
   - Render handles zero-downtime upgrades

### Monitoring & Logs

1. **Render Logs**:
   ```
   Dashboard → recoverx-api → Logs
   - Deployment logs
   - Application output
   - Error messages
   ```

2. **Database Connections**:
   ```
   Dashboard → recoverx-postgres → Settings
   - Active connections
   - Query performance
   ```

3. **Redis Cache**:
   ```
   Dashboard → recoverx-redis → Monitoring
   - Memory usage
   - Hit/miss rate
   ```

## Troubleshooting

### "Production configuration is incomplete" error

**Fix**: Ensure all required secrets are set in Render environment:
```
AUTH_SECRET, RAZORPAY_WEBHOOK_SECRET, BOOTSTRAP_ADMIN_PASSWORD
```

### "alembic upgrade head" fails

**Fix**: 
1. Check PostgreSQL is running: `SELECT 1;`
2. Verify CONNECTION_STRING in logs
3. Check migrations exist: `ls backend/alembic/versions/`
4. Manually run migration (via Render shell)

### "Invalid webhook signature"

**Fix**:
1. Verify `RAZORPAY_WEBHOOK_SECRET` matches Razorpay Dashboard
2. Check Razorpay is sending correct `X-Razorpay-Signature` header
3. Test locally first with curl

### E2E tests fail

**Fix**:
1. Verify frontend and API URLs are correct
2. Ensure test admin account exists
3. Check auth tokens work: `curl -H "Authorization: Bearer $TOKEN" /recovery-cases`
4. Look at Playwright trace: `npx playwright show-trace trace.zip`

## Going to Real Razorpay

When ready to use live Razorpay:

1. **Get Live Credentials**:
   ```
   Razorpay Dashboard → Settings → API Keys
   - Key ID: rzp_live_...
   - Key Secret: ...
   ```

2. **Update Environment**:
   ```
   RAZORPAY_KEY_ID=rzp_live_...
   RAZORPAY_KEY_SECRET=...
   PAYMENT_PROVIDER=live  (if you implement real provider)
   ```

3. **Set Up Live Webhook**:
   ```
   Razorpay Dashboard → Webhooks
   - URL: https://recoverx-api-xxxxx.onrender.com/webhooks/razorpay
   - Secret: Your RAZORPAY_WEBHOOK_SECRET
   ```

4. **Test with Real Payments**:
   - Create a test payment link
   - Pay with test card: 4111 1111 1111 1111
   - Verify webhook triggers
   - Check case updates to RECOVERED

## Performance & Scaling

### Optimize for Growth

1. **Database Queries**:
   - Add indexes for common filters
   - Monitor slow queries in Render logs
   - Archive old completed cases

2. **Redis Cache**:
   - Cache frequent analytics queries
   - Session storage (already using)
   - Rate limiting (can implement)

3. **Horizontal Scaling**:
   - Render allows multiple instances
   - Set `numInstances: 2+` in render.yaml
   - Load balancer auto-distributes

4. **Background Tasks**:
   - Enable TEMPORAL_ENABLED=true for durable workflows
   - Run worker on separate instance
   - Queue payment link send operations

## Security Best Practices

1. **Never Log Secrets**:
   - AUTH_SECRET, RAZORPAY_KEY_SECRET, etc. should never appear in logs
   - Config validation enforces this ✅

2. **HTTPS Only**:
   - Render auto-provides HTTPS certificates
   - Set CORS_ORIGINS to https:// URLs only

3. **Regular Audits**:
   - Check `/audit-events` endpoint for suspicious activity
   - Review auth session logs weekly

4. **Update Dependencies**:
   ```bash
   cd backend
   pip list --outdated
   pip install --upgrade [package]
   cd ../frontend
   npm outdated
   npm update
   ```

5. **Backup Strategy**:
   - Enable database automatic backups (Render default)
   - Test restore process quarterly

## Going Live Checklist

- [ ] All secrets configured in Render
- [ ] Database migration ran successfully
- [ ] Bootstrap admin created and can login
- [ ] Webhook configured in Razorpay
- [ ] SSL certificate active (Render auto)
- [ ] CORS_ORIGINS set to deployed frontend URL
- [ ] E2E tests pass against deployed instance
- [ ] Health check returns OK
- [ ] Database backups enabled
- [ ] Error monitoring configured (optional: Sentry)
- [ ] Team members have login credentials
- [ ] Documentation shared with team

## Support & Troubleshooting

For issues:
1. Check Render logs first
2. Review this guide's troubleshooting section
3. Test locally with docker-compose
4. Check environment variables match .env.production.example
5. Verify Razorpay webhook secret matches Dashboard

## Next Steps

1. Deploy to Render using render.yaml
2. Configure environment variables
3. Set up Razorpay webhooks
4. Run E2E test suite against deployed instance
5. Create additional admin/operator users
6. Import real customer data (if available)
7. Monitor for 24 hours before heavy use
