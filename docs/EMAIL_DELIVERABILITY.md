# Email deliverability

Transactional email (verification, password reset, billing notices) only works if
it reaches the inbox. Two things get you there: **DNS authentication** so mailbox
providers trust your domain, and a **suppression list** so you stop mailing dead or
hostile addresses (which is what wrecks a sender reputation).

The app handles suppression for you (see below). DNS is a one-time setup you do at
your registrar / DNS host.

## 1. DNS authentication (do this once)

Set these records for the domain in `EMAIL_FROM`. Exact values come from your email
provider (SES, Postmark, Mailgun, Resend, Google Workspace…).

| Record | Type | Purpose | Example value |
|---|---|---|---|
| **SPF** | TXT on `@` | Lists servers allowed to send as your domain | `v=spf1 include:amazonses.com ~all` |
| **DKIM** | CNAME(s) | Cryptographically signs each message | provider gives you 1–3 CNAMEs |
| **DMARC** | TXT on `_dmarc` | Tells inboxes what to do when SPF/DKIM fail, and where to report | `v=DMARC1; p=quarantine; rua=mailto:dmarc@yourdomain.com; adkim=s; aspf=s` |

Notes:
- **Without DMARC, billing and reset emails increasingly land in spam** — Gmail/Yahoo
  now require it for bulk senders.
- Start DMARC at `p=none` (monitor only), read the aggregate reports for a week, then
  move to `p=quarantine` and finally `p=reject` once SPF+DKIM pass cleanly.
- Send from a **subdomain** (e.g. `mail.yourdomain.com`) so a deliverability problem
  never taints your root domain's reputation.
- Verify with: `dig TXT yourdomain.com`, `dig TXT _dmarc.yourdomain.com`, and any
  "check your DKIM" tool your provider offers.

## 2. Suppression list (built in)

`send_email()` checks `suppressed_emails` before every send and silently skips any
address on it. Addresses get there via your provider's bounce/complaint webhook.

### Wire up the webhook

1. Set `EMAIL_WEBHOOK_SECRET` in `.env` to a long random string.
2. In your ESP dashboard, point bounce + complaint webhooks at:
   ```
   POST https://yourdomain.com/webhooks/email?token=<EMAIL_WEBHOOK_SECRET>
   ```
   (or send the token as an `X-Webhook-Token` header instead of the query param).

The endpoint understands, out of the box:
- **Postmark** — Bounce and SpamComplaint webhooks.
- **AWS SES via SNS** — Bounce and Complaint notifications.
- **Generic** — any `{"email": "...", "reason": "bounce|complaint|manual"}` body,
  or a JSON array of them. Point any other provider (Mailgun, Resend, Sendgrid…) at
  this shape with a tiny transform, or extend `parse_provider_payload()` in
  `app/services/suppression.py`.

> AWS SNS also sends a one-off `SubscriptionConfirmation` when you first attach the
> topic. Confirm it once (open its `SubscribeURL`); the app ignores it safely.

### Managing the list manually

```python
from app.services import suppression
await suppression.suppress(db, "user@example.com", reason="manual")
await suppression.unsuppress(db, "user@example.com")   # e.g. after a user fixes their mailbox
```

## 3. Sanity checklist before launch

- [ ] SPF, DKIM, DMARC all pass (send a test to a Gmail account → "Show original").
- [ ] `EMAIL_FROM` uses your authenticated domain, not `example.com`.
- [ ] `EMAIL_WEBHOOK_SECRET` set and the ESP webhook is delivering (check its logs).
- [ ] A hard-bounced test address shows up in `suppressed_emails`.
- [ ] Reverse DNS / PTR set if you send from your own MTA (not needed with an ESP).
