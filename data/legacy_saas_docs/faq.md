# Frequently Asked Questions

## General

### How do I reset my password?
Go to Login > Forgot Password. Enter your email. Check your inbox for a reset link (valid for 30 minutes).

### How do I change my plan?
Go to Settings > Billing > Change Plan. Upgrade takes effect immediately. Downgrade takes effect at the end of the billing cycle.

### Can I cancel anytime?
Yes. Go to Settings > Billing > Cancel Subscription. You retain access until the end of the billing period.

## Sync

### Why is my sync not working?
Check: 1) Connected providers are authenticated, 2) You have available storage, 3) The files are not locked by another process.

### How do I resolve sync conflicts?
When a conflict occurs, CloudSync creates a duplicate file with "(conflict)" in the name. You can choose which version to keep in the web UI.

### What file types are supported for sync?
All file types are supported. File size limits: Free (100MB), Pro (5GB), Enterprise (50GB).

## Security

### Does CloudSync encrypt my data?
Yes. Data is encrypted in transit (TLS 1.3) and at rest (AES-256). Enterprise plans get customer-managed encryption keys.

### How do I enable two-factor authentication?
Go to Settings > Security > Two-Factor Authentication. Choose authenticator app or SMS. Enter the verification code to confirm.

## API

### How do I get an API Key?
Go to Console > Developer Settings > API Keys > Generate New Key. Copy the key immediately — it won't be shown again.

### Why am I getting a 403 error?
403 errors mean access denied. Common causes: 1) Invalid or expired API Key, 2) Domain not whitelisted, 3) CORS configuration missing.
