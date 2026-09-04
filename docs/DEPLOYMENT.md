# Deployment

Local development uses `docker-compose.yml` with frontend, backend, PostgreSQL, and Redis. Render configuration is in `render.yaml`. Set `DATABASE_URL`, `REDIS_URL`, `RAZORPAY_WEBHOOK_SECRET`, `AUTH_SECRET`, and provider credentials through the deployment secret store. Authentication is secure-by-default; local demo credentials are not production credentials.

Set `PAYMENT_PROVIDER=simulated` for local demos. Set `PAYMENT_PROVIDER=razorpay` only after supplying `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` through the deployment secret store. All provider actions still pass through the RecoverX Tool Gateway and policy engine.