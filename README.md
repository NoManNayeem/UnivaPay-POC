# UnivaPay POC (Flask + Next.js)

This repository demonstrates a **minimal proof of concept** integrating **UnivaPay** with a Flask backend and a Next.js frontend.

---

## Stack

- **Backend (Flask)**
  - User auth (hardcoded POC credentials: `Nayeem` / `password`)
  - SQLite DB with tables: `payments`, `provider_payments`, `webhook_events`
  - Endpoints for login, payments, checkout (UnivaPay charges & subscriptions), webhook receiver
  - Auto-status refresh via background poller

- **Frontend (Next.js + Tailwind)**
  - App router, client components
  - Login → Home → Buy or Subscribe → Payments
  - Integrated UnivaPay JS widget (`checkout.js`) for tokenization & hosted checkout
  - Payments page shows local + provider status, auto-refresh after 3DS return

---

## Setup

### Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate   # (Windows: venv\Scripts\activate)
pip install -r requirements.txt

# .env configuration
PORT=5000
SECRET_KEY=dev-secret
DATABASE_URL=sqlite:///poc.db

# UnivaPay keys
UNIVAPAY_APP_TOKEN=...
UNIVAPAY_APP_SECRET=...
UNIVAPAY_STORE_ID=...
UNIVAPAY_WEBHOOK_AUTH=some-shared-secret

# Run server
python app.py
```

### Frontend
```bash
cd frontend
npm install

# .env.local configuration
NEXT_PUBLIC_API_BASE=http://localhost:5000
NEXT_PUBLIC_UNIVAPAY_APP_ID=...
NEXT_PUBLIC_UNIVAPAY_RETURN_URL=http://127.0.0.1:3000/payments/return

# Run dev server
npm run dev
```

---

## Payment Flow

### One-Time Purchase
1. User logs in → navigates to **Buy Products** page.
2. User enters item & amount → clicks **Pay with UnivaPay**.
3. FE opens UnivaPay widget in `token` mode → returns `transaction_token_id`.
4. FE sends token + details to **BE `/api/checkout/charge`**.
5. BE calls **UnivaPay Charges API** → creates charge.
6. Local DB row (`payments`, `provider_payments`) is saved.
7. If 3DS required, UnivaPay redirects back to **Return URL**.
8. Webhook / poller updates status from `pending` → `successful`/`failed`.
9. User sees updated status in **Payments** page.

### Subscription
1. User logs in → navigates to **Subscribe** page.
2. User selects Monthly or 6-Month plan → FE opens UnivaPay widget in `token` mode (`subscription`).
3. Widget returns `transaction_token_id`.
4. FE sends token + plan to **BE `/api/checkout/subscription`**.
5. BE calls **UnivaPay Subscriptions API** → creates subscription.
6. Local DB row is saved, linked provider ID recorded.
7. Webhook / poller updates subscription status (e.g., `current`).
8. User sees subscription entry in **Payments** page.

---

## Test Credentials

- POC Login:  
  `username`: **Nayeem**  
  `password`: **password**

- For UnivaPay: use your test keys and cards provided in the UnivaPay dashboard.

---

## Notes

- This is a **POC only**: no production-grade auth, error handling, or security hardening.
- Webhooks must be exposed (e.g., via **ngrok**) for UnivaPay to deliver events locally.
