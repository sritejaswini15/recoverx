# API

Core endpoints are `POST /webhooks/razorpay`, `GET /recovery-cases`, `GET /recovery-cases/{id}`, `POST /recovery-cases/{id}/execute`, `POST /recovery-cases/{id}/stop`, `GET /analytics/recovery`, `GET /escalations`, `GET/PUT /policies`, `GET /audit-events`, `GET /customers`, and `POST /simulation/*`.

Dashboard endpoints require bearer authentication. Webhooks require `X-Razorpay-Signature` using HMAC-SHA256 and are idempotent by payload digest.

Recovery actions create an opaque, expiring customer payment URL during payment-link execution. The authenticated case detail response exposes this URL as `payment_link.payment_url`; the public customer page accepts only its token at `GET/POST /pay/{token}`. The unhashed token is never reconstructed from a case ID or returned by the payment-link metadata endpoint.