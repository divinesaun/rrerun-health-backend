# RERUN Health AI — FastAPI Backend

Two-sided marketplace connecting customers (via WhatsApp) with pharmacies (via web dashboard) in Zimbabwe.

## Architecture

```
Customer (WhatsApp) → Twilio → FastAPI → Supabase
                                  ↕
                         OCR.space + Step 3.5 Flash (OpenRouter)
                                  ↕
Pharmacy (Dashboard) → FastAPI → Supabase
```

## Quick Start

### 1. Install Dependencies

```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

**Required keys:**
- `SUPABASE_URL` / `SUPABASE_KEY` — Your Supabase project
- `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` — Twilio WhatsApp
- `OPENROUTER_API_KEY` — For Step 3.5 Flash NLU
- `OCRSPACE_API_KEY` — Use `"helloworld"` for free dev testing
- `JWT_SECRET_KEY` — Random secret for JWT signing
- `ADMIN_EMAIL` / `ADMIN_PASSWORD` — Seeded on first startup

### 3. Set Up Supabase Tables

Create these tables in your Supabase project:

- `admins` — id, email, password_hash, name, role, created_at
- `customers` — id, phone, name, created_at
- `pharmacies` — id, name, address, suburb, phone, email, whatsapp_number, operating_hours, is_active, latitude, longitude, created_at
- `pharmacy_users` — id, email, password_hash, pharmacy_id (FK), name, role, must_change_password, created_at
- `medicines` — id, name, generic_name, category, dosage_form, strength, description, requires_prescription, created_at
- `inventory` — id, pharmacy_id (FK), medicine_id (FK), price, in_stock, quantity_available, times_searched, last_search_date, created_at
- `search_logs` — id, customer_id (FK), query, results_count, medicine_ids, created_at
- `inquiries` — id, customer_id (FK), pharmacy_id (FK), medicine_id (FK), message, created_at
- `conversation_history` — id, customer_id (FK), role, content, created_at
- `pharmacy_analytics` — id, pharmacy_id (FK), total_searches, total_inquiries, created_at

### 4. Run the Server

```bash
uvicorn app.main:app --reload --port 8000
```

API docs available at: `http://localhost:8000/docs`

### 5. Run Tests

```bash
pytest tests/ -v
```

## API Endpoints

### Health
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/docs` | Swagger API docs |

### WhatsApp (Twilio Webhooks)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/webhook/whatsapp` | Receive incoming WhatsApp messages |
| POST | `/webhook/whatsapp/status` | Twilio delivery receipts |
| POST | `/api/whatsapp/send` | Send outbound messages |

### Customer
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/customers/auth` | Auto-create/login by phone |
| GET | `/api/customers/me?phone=` | Get customer profile |
| GET | `/api/customers/me/history?phone=` | Search history |
| POST | `/api/customers/inquiry` | Log pharmacy inquiry |

### Admin (requires admin JWT)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/admin/auth/login` | Admin login |
| GET | `/api/admin/auth/me` | Admin profile |
| GET | `/api/admin/pharmacies` | List all pharmacies |
| POST | `/api/admin/pharmacies` | Create pharmacy + user |
| PUT | `/api/admin/pharmacies/{id}` | Edit pharmacy |
| DELETE | `/api/admin/pharmacies/{id}` | Deactivate pharmacy |
| GET | `/api/admin/pharmacies/{id}/users` | Pharmacy users |
| POST | `/api/admin/pharmacies/{id}/resend-credentials` | Resend login email |
| GET | `/api/admin/users` | All pharmacy users |
| DELETE | `/api/admin/users/{id}` | Remove user |
| POST | `/api/admin/users/{id}/reset-password` | Reset password |

### Pharmacy Dashboard (requires pharmacy JWT)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/pharmacy/auth/login` | Pharmacy login |
| POST | `/api/pharmacy/auth/logout` | Logout |
| GET | `/api/pharmacy/auth/me` | Current user |
| POST | `/api/pharmacy/auth/change-password` | Change password |
| GET | `/api/pharmacy/inventory` | List inventory |
| POST | `/api/pharmacy/inventory` | Add item |
| PUT | `/api/pharmacy/inventory/{id}` | Update item |
| DELETE | `/api/pharmacy/inventory/{id}` | Delete item |
| POST | `/api/pharmacy/inventory/bulk-upload` | CSV upload |
| GET | `/api/pharmacy/medicines/search` | Search master list |
| GET | `/api/pharmacy/analytics` | Dashboard stats |
| GET | `/api/pharmacy/analytics/trending` | Trending medicines |
| GET | `/api/pharmacy/inquiries` | Customer inquiries |
| GET | `/api/pharmacy/profile` | Pharmacy profile |
| PUT | `/api/pharmacy/profile` | Update profile |

### Medicine Search & Discovery (public)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/search` | Main search endpoint |
| GET | `/api/medicines` | List medicines |
| GET | `/api/medicines/{id}` | Medicine details |
| GET | `/api/medicines/{id}/alternatives` | Alternatives |
| GET | `/api/medicines/{id}/availability` | Availability |
| GET | `/api/pharmacies` | List pharmacies |
| GET | `/api/pharmacies/{id}` | Pharmacy details |
| GET | `/api/pharmacies/nearby` | Nearby pharmacies |

## Twilio WhatsApp Setup

1. Create a Twilio account at [twilio.com](https://www.twilio.com)
2. Activate the WhatsApp Sandbox in Console → Messaging → Try WhatsApp
3. Set the webhook URL to `https://your-domain.com/webhook/whatsapp`
4. Set the status callback URL to `https://your-domain.com/webhook/whatsapp/status`
5. For local dev, use [ngrok](https://ngrok.com) to expose your local server

## OCR.space Setup

- Free tier: 25,000 requests/month using API key `"helloworld"`
- Production: Register at [ocr.space/ocrapi](https://ocr.space/ocrapi) for a dedicated key
- OCR Engine 2 recommended for printed prescriptions

## OpenRouter Setup

1. Get an API key at [openrouter.ai](https://openrouter.ai)
2. Set `OPENROUTER_API_KEY` in `.env`
3. Free tier model: `stepfun/step-3.5-flash:free`
4. Paid tier model: `stepfun/step-3.5-flash`

## Admin Setup

The admin account is **seeded automatically** on first startup using `ADMIN_EMAIL` and `ADMIN_PASSWORD` from `.env`. There is no admin registration endpoint — this is by design.

## Email Setup

**SMTP (default):** Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` in `.env`.

**SendGrid:** Set `SENDGRID_API_KEY` and `EMAIL_PROVIDER=sendgrid` in `.env`.

Welcome emails are sent automatically when the admin creates a new pharmacy.

## Deployment

### Railway
```bash
railway init
railway up
```

### Render
1. Connect your GitHub repo
2. Set build command: `pip install -r requirements.txt`
3. Set start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Add environment variables in the Render dashboard

## Project Structure

```
backend/
├── app/
│   ├── main.py              # FastAPI app, lifespan, router registration
│   ├── config.py            # Environment variable settings
│   ├── database.py          # Supabase client + all DB operations
│   ├── models/              # Pydantic request/response models
│   ├── routers/             # API route handlers
│   ├── services/            # Business logic (OCR, AI, Twilio, email, search)
│   └── utils/               # Security, validators, helpers
├── tests/                   # pytest test suite
├── requirements.txt
├── .env.example
└── README.md
```
