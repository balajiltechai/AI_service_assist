"""
Seed script — populates APIPlatform API (registry data) and SQLite (AI-generated docs).

Run from project root:
    python -m backend.seed_data

Requires the APIPlatform server to be running on port 8001:
    python run_api_platform.py
"""
import asyncio
import json
import httpx
from datetime import datetime, timedelta
from pathlib import Path

import aiosqlite


DB_PATH = Path(__file__).parent / "service_assist.db"
API_PLATFORM_URL = "http://localhost:8001"

# ── helpers ──────────────────────────────────────────────────────────────────

def ts(days_ago=0, hours_ago=0):
    return (datetime.utcnow() - timedelta(days=days_ago, hours=hours_ago)).isoformat()


# ── Sample OpenAPI specs ──────────────────────────────────────────────────────

PAYMENT_SPEC_V1 = json.dumps({
    "openapi": "3.0.0",
    "info": {"title": "Payment Service", "version": "v1", "description": ""},
    "servers": [{"url": "https://api.acme.com/payments/v1"}],
    "paths": {
        "/charge": {"post": {"summary": "", "tags": ["Payments"],
            "security": [{"bearerAuth": []}],
            "requestBody": {"content": {"application/json": {"schema": {
                "type": "object",
                "properties": {
                    "amount": {"type": "integer"},
                    "currency": {"type": "string"},
                    "source": {"type": "string"}
                }, "required": ["amount", "currency", "source"]}}}},
            "responses": {"200": {"description": "ok"}}}},
        "/refunds/{chargeId}": {"post": {"summary": "", "deprecated": True,
            "parameters": [{"name": "chargeId", "in": "path", "required": True,
                            "schema": {"type": "string"}}],
            "responses": {"200": {"description": "ok"}}}},
        "/charges/{id}": {"get": {"summary": "", "responses": {"200": {"description": "ok"}}}},
        "/balance": {"get": {"summary": "", "responses": {"200": {"description": "ok"}}}},
    },
    "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}}
}, indent=2)

PAYMENT_SPEC_V2 = json.dumps({
    "openapi": "3.0.0",
    "info": {"title": "Payment Service", "version": "v2",
             "description": "Handles all payment processing for the ACME platform"},
    "servers": [{"url": "https://api.acme.com/payments/v2"}],
    "paths": {
        "/charges": {
            "post": {"summary": "Create a charge", "tags": ["Charges"],
                "security": [{"bearerAuth": []}],
                "requestBody": {"content": {"application/json": {"schema": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": "integer", "example": 2999},
                        "currency": {"type": "string", "example": "USD"},
                        "source": {"type": "string", "example": "tok_visa"},
                        "capture": {"type": "boolean", "default": True},
                        "metadata": {"type": "object"}
                    }, "required": ["amount", "currency", "source"]}}}},
                "responses": {"200": {"description": "Charge created"}, "402": {"description": "Payment failed"}}},
            "get": {"summary": "List charges", "tags": ["Charges"],
                "parameters": [
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 10}},
                    {"name": "customer_id", "in": "query", "schema": {"type": "string"}},
                    {"name": "created_after", "in": "query", "schema": {"type": "string", "format": "date-time"}}
                ],
                "responses": {"200": {"description": "List of charges"}}}
        },
        "/charges/{chargeId}": {
            "get": {"summary": "Retrieve a charge", "tags": ["Charges"],
                "responses": {"200": {"description": "Charge object"}, "404": {"description": "Not found"}}},
            "patch": {"summary": "Update charge metadata", "tags": ["Charges"],
                "responses": {"200": {"description": "Updated charge"}}}
        },
        "/charges/{chargeId}/capture": {
            "post": {"summary": "Capture an authorized charge", "tags": ["Charges"],
                "responses": {"200": {"description": "Captured"}}}
        },
        "/refunds": {
            "post": {"summary": "Create a refund", "tags": ["Refunds"],
                "requestBody": {"content": {"application/json": {"schema": {
                    "type": "object",
                    "properties": {
                        "charge_id": {"type": "string"},
                        "amount": {"type": "integer"},
                        "reason": {"type": "string", "enum": ["duplicate", "fraudulent", "requested_by_customer"]}
                    }, "required": ["charge_id"]}}}},
                "responses": {"200": {"description": "Refund created"}}}
        },
        "/customers": {
            "post": {"summary": "Create a customer", "tags": ["Customers"],
                "responses": {"200": {"description": "Customer created"}}},
            "get": {"summary": "List customers", "tags": ["Customers"],
                "responses": {"200": {"description": "List of customers"}}}
        },
        "/customers/{customerId}/payment-methods": {
            "get": {"summary": "List saved payment methods", "tags": ["Customers"],
                "responses": {"200": {"description": "Payment methods"}}},
            "post": {"summary": "Attach a payment method", "tags": ["Customers"],
                "responses": {"200": {"description": "Attached"}}}
        },
        "/webhooks": {
            "post": {"summary": "Register a webhook endpoint", "tags": ["Webhooks"],
                "responses": {"201": {"description": "Webhook registered"}}},
            "get": {"summary": "List webhooks", "tags": ["Webhooks"],
                "responses": {"200": {"description": "Webhooks list"}}}
        },
        "/balance": {
            "get": {"summary": "Retrieve account balance", "tags": ["Balance"],
                "responses": {"200": {"description": "Balance object"}}}
        },
        "/payouts": {
            "post": {"summary": "Create a payout", "tags": ["Payouts"],
                "responses": {"200": {"description": "Payout created"}}},
            "get": {"summary": "List payouts", "tags": ["Payouts"],
                "responses": {"200": {"description": "Payouts list"}}}
        }
    },
    "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}}
}, indent=2)

AUTH_SPEC_V2 = json.dumps({
    "openapi": "3.0.0",
    "info": {"title": "Auth Service", "version": "v2", "description": "Identity and access management"},
    "servers": [{"url": "https://api.acme.com/auth/v2"}],
    "paths": {
        "/login": {"post": {"summary": "Authenticate user", "tags": ["Auth"],
            "requestBody": {"content": {"application/json": {"schema": {
                "type": "object",
                "properties": {"email": {"type": "string"}, "password": {"type": "string"}},
                "required": ["email", "password"]}}}},
            "responses": {"200": {"description": "JWT tokens returned"}, "401": {"description": "Invalid credentials"}}}},
        "/logout": {"post": {"summary": "Invalidate session", "tags": ["Auth"],
            "security": [{"bearerAuth": []}], "responses": {"204": {"description": "Logged out"}}}},
        "/refresh": {"post": {"summary": "Refresh access token", "tags": ["Auth"],
            "responses": {"200": {"description": "New access token"}, "401": {"description": "Expired refresh token"}}}},
        "/me": {"get": {"summary": "Get current user profile", "tags": ["Profile"],
            "security": [{"bearerAuth": []}], "responses": {"200": {"description": "User profile"}}}},
        "/users": {"post": {"summary": "Register a new user", "tags": ["Users"],
            "responses": {"201": {"description": "User created"}, "409": {"description": "Email exists"}}}},
        "/users/{userId}/roles": {
            "get": {"summary": "Get user roles", "tags": ["RBAC"],
                "security": [{"bearerAuth": []}], "responses": {"200": {"description": "Roles list"}}},
            "put": {"summary": "Set user roles", "tags": ["RBAC"],
                "security": [{"bearerAuth": []}], "responses": {"200": {"description": "Roles updated"}}}
        },
        "/oauth/authorize": {"get": {"summary": "OAuth2 authorization endpoint", "tags": ["OAuth"],
            "responses": {"302": {"description": "Redirect to provider"}}}},
        "/oauth/callback": {"get": {"summary": "OAuth2 callback handler", "tags": ["OAuth"],
            "responses": {"200": {"description": "Tokens issued"}}}},
        "/verify-email": {"post": {"summary": "Verify email address", "tags": ["Users"],
            "responses": {"200": {"description": "Email verified"}}}},
        "/forgot-password": {"post": {"summary": "Initiate password reset", "tags": ["Users"],
            "responses": {"200": {"description": "Reset email sent"}}}},
        "/reset-password": {"post": {"summary": "Complete password reset", "tags": ["Users"],
            "responses": {"200": {"description": "Password updated"}}}},
    },
    "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}}
}, indent=2)

ORDER_SPEC_V1 = json.dumps({
    "openapi": "3.0.0",
    "info": {"title": "Order Service", "version": "v1", "description": "Order lifecycle management"},
    "servers": [{"url": "https://api.acme.com/orders/v1"}],
    "paths": {
        "/orders": {
            "post": {"summary": "Place a new order", "tags": ["Orders"],
                "security": [{"bearerAuth": []}],
                "responses": {"201": {"description": "Order created"}, "400": {"description": "Invalid order"}}},
            "get": {"summary": "List orders", "tags": ["Orders"],
                "responses": {"200": {"description": "Orders list"}}}
        },
        "/orders/{orderId}": {
            "get": {"summary": "Get order details", "tags": ["Orders"],
                "responses": {"200": {"description": "Order object"}}},
            "patch": {"summary": "Update order status", "tags": ["Orders"],
                "responses": {"200": {"description": "Updated order"}}}
        },
        "/orders/{orderId}/cancel": {"post": {"summary": "Cancel an order", "tags": ["Orders"],
            "responses": {"200": {"description": "Cancelled"}}}},
        "/orders/{orderId}/tracking": {"get": {"summary": "Get shipping tracking info", "tags": ["Shipping"],
            "responses": {"200": {"description": "Tracking data"}}}},
        "/cart": {
            "get": {"summary": "Get current cart", "tags": ["Cart"], "responses": {"200": {"description": "Cart"}}},
            "post": {"summary": "Add item to cart", "tags": ["Cart"], "responses": {"200": {"description": "Cart updated"}}},
            "delete": {"summary": "Clear cart", "tags": ["Cart"], "responses": {"204": {"description": "Cleared"}}}
        },
        "/cart/{itemId}": {
            "patch": {"summary": "Update cart item quantity", "tags": ["Cart"],
                "responses": {"200": {"description": "Updated"}}},
            "delete": {"summary": "Remove cart item", "tags": ["Cart"],
                "responses": {"204": {"description": "Removed"}}}
        }
    },
    "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}}
}, indent=2)

NOTIFICATION_SPEC_V1 = json.dumps({
    "openapi": "3.0.0",
    "info": {"title": "Notification Service", "version": "v1",
             "description": "Multi-channel notification delivery (email, SMS, push)"},
    "servers": [{"url": "https://api.acme.com/notifications/v1"}],
    "paths": {
        "/send": {"post": {"summary": "Send a notification", "tags": ["Notifications"],
            "security": [{"apiKey": []}],
            "responses": {"202": {"description": "Notification queued"}}}},
        "/send/batch": {"post": {"summary": "Send bulk notifications", "tags": ["Notifications"],
            "responses": {"202": {"description": "Batch queued"}}}},
        "/templates": {
            "get": {"summary": "List notification templates", "tags": ["Templates"],
                "responses": {"200": {"description": "Templates list"}}},
            "post": {"summary": "Create a template", "tags": ["Templates"],
                "responses": {"201": {"description": "Template created"}}}
        },
        "/templates/{templateId}": {
            "get": {"summary": "Get template", "tags": ["Templates"], "responses": {"200": {"description": "Template"}}},
            "put": {"summary": "Update template", "tags": ["Templates"], "responses": {"200": {"description": "Updated"}}},
            "delete": {"summary": "Delete template", "tags": ["Templates"], "responses": {"204": {"description": "Deleted"}}}
        },
        "/notifications/{notificationId}": {"get": {"summary": "Get notification status", "tags": ["Status"],
            "responses": {"200": {"description": "Notification status"}}}},
        "/preferences/{userId}": {
            "get": {"summary": "Get user notification preferences", "tags": ["Preferences"],
                "responses": {"200": {"description": "Preferences"}}},
            "put": {"summary": "Update notification preferences", "tags": ["Preferences"],
                "responses": {"200": {"description": "Updated"}}}
        },
        "/unsubscribe": {"post": {"summary": "Global unsubscribe", "tags": ["Preferences"],
            "responses": {"200": {"description": "Unsubscribed"}}}},
        "/email/send": {"post": {"summary": "Send email (legacy)", "deprecated": True, "tags": ["Legacy"],
            "responses": {"200": {"description": "Sent"}}}},
        "/sms/send": {"post": {"summary": "Send SMS (legacy)", "deprecated": True, "tags": ["Legacy"],
            "responses": {"200": {"description": "Sent"}}}},
    },
    "components": {"securitySchemes": {"apiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"}}}
}, indent=2)

INVENTORY_SPEC_V1 = json.dumps({
    "openapi": "3.0.0",
    "info": {"title": "Inventory Service", "version": "v1",
             "description": "Real-time inventory tracking and warehouse management"},
    "servers": [{"url": "https://api.acme.com/inventory/v1"}],
    "paths": {
        "/products": {
            "get": {"summary": "List products", "tags": ["Products"], "responses": {"200": {"description": "Products"}}},
            "post": {"summary": "Create product", "tags": ["Products"], "responses": {"201": {"description": "Created"}}}
        },
        "/products/{productId}": {
            "get": {"summary": "Get product", "tags": ["Products"], "responses": {"200": {"description": "Product"}}},
            "put": {"summary": "Update product", "tags": ["Products"], "responses": {"200": {"description": "Updated"}}},
            "delete": {"summary": "Archive product", "tags": ["Products"], "responses": {"204": {"description": "Archived"}}}
        },
        "/products/{productId}/stock": {
            "get": {"summary": "Get current stock level", "tags": ["Stock"], "responses": {"200": {"description": "Stock info"}}},
            "patch": {"summary": "Adjust stock level", "tags": ["Stock"], "responses": {"200": {"description": "Stock adjusted"}}}
        },
        "/warehouses": {
            "get": {"summary": "List warehouses", "tags": ["Warehouses"], "responses": {"200": {"description": "Warehouses"}}},
            "post": {"summary": "Register warehouse", "tags": ["Warehouses"], "responses": {"201": {"description": "Registered"}}}
        },
        "/warehouses/{warehouseId}/inventory": {"get": {"summary": "Get warehouse inventory",
            "tags": ["Warehouses"], "responses": {"200": {"description": "Inventory list"}}}},
        "/reservations": {
            "post": {"summary": "Reserve stock for order", "tags": ["Reservations"],
                "responses": {"200": {"description": "Reserved"}, "409": {"description": "Insufficient stock"}}},
            "delete": {"summary": "Release reservation", "tags": ["Reservations"],
                "responses": {"204": {"description": "Released"}}}
        },
        "/alerts": {
            "get": {"summary": "Get low-stock alerts", "tags": ["Alerts"], "responses": {"200": {"description": "Alerts"}}},
            "post": {"summary": "Create stock alert rule", "tags": ["Alerts"], "responses": {"201": {"description": "Alert rule created"}}}
        }
    },
    "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}}
}, indent=2)


# ── Pre-generated documentation (seeded into SQLite) ─────────────────────────

PAYMENT_DOC_V1 = {
    "service_id": "payment-service", "name": "Payment Service", "version": "v1",
    "summary": "Handles basic payment processing including charges and refunds for the ACME platform.",
    "description": (
        "The Payment Service (v1) provides foundational payment processing functionality. "
        "It exposes endpoints for creating charges, processing refunds, and checking account balances. "
        "This version was the initial implementation built on Stripe's API and is now in maintenance mode.\n\n"
        "Note: v1 lacks customer management, webhook support, and advanced payout features. "
        "Teams are strongly encouraged to migrate to v2."
    ),
    "base_url": "https://api.acme.com/payments/v1",
    "endpoints": [
        {
            "method": "POST", "path": "/charge",
            "summary": "Create a payment charge",
            "description": "Initiates a payment charge against a tokenized payment source. Amount must be in the smallest currency unit (cents).",
            "authentication": "Bearer JWT token with `payments:write` scope.",
            "sample_request": json.dumps({"amount": 2999, "currency": "USD", "source": "tok_visa"}, indent=2),
            "sample_response": json.dumps({"id": "ch_1a2b3c", "status": "succeeded", "amount": 2999, "currency": "USD"}, indent=2),
            "is_deprecated": False, "deprecation_notice": None, "parameters": [], "tags": ["Payments"]
        },
        {
            "method": "POST", "path": "/refunds/{chargeId}",
            "summary": "Refund a charge (deprecated)",
            "description": "Processes a full refund for a given charge ID. Deprecated — use POST /refunds in v2.",
            "authentication": "Bearer JWT token required.",
            "sample_request": None,
            "sample_response": json.dumps({"id": "re_abc123", "status": "succeeded", "charge": "ch_1a2b3c"}, indent=2),
            "is_deprecated": True,
            "deprecation_notice": "Deprecated as of 2024-01-01. Migrate to POST /refunds in v2. Will be removed in v3.",
            "parameters": [{"name": "chargeId", "in": "path", "required": True}], "tags": ["Refunds"]
        },
        {
            "method": "GET", "path": "/charges/{id}",
            "summary": "Retrieve a charge by ID",
            "description": "Fetches the full details of a charge including status, amount, metadata, and timeline events.",
            "authentication": "Bearer JWT token with `payments:read` scope.",
            "sample_request": None,
            "sample_response": json.dumps({"id": "ch_1a2b3c", "status": "succeeded", "amount": 2999, "refunded": False}, indent=2),
            "is_deprecated": False, "deprecation_notice": None,
            "parameters": [{"name": "id", "in": "path", "required": True}], "tags": ["Payments"]
        },
        {
            "method": "GET", "path": "/balance",
            "summary": "Retrieve account balance",
            "description": "Returns the current available and pending balance for your account.",
            "authentication": "Bearer JWT token required.",
            "sample_request": None,
            "sample_response": json.dumps({"available": [{"amount": 150000, "currency": "USD"}]}, indent=2),
            "is_deprecated": False, "deprecation_notice": None, "parameters": [], "tags": ["Balance"]
        }
    ],
    "authentication_requirements": (
        "All endpoints require a Bearer JWT token in the Authorization header. "
        "Tokens are issued by the Auth Service at POST /auth/v2/login. "
        "Write operations require `payments:write` scope; reads require `payments:read`."
    ),
    "capabilities": ["Create and capture payment charges", "Process full refunds", "Query charge details", "Retrieve account balance"],
    "tags": ["Payments", "Refunds", "Balance"],
    "generated_at": ts(days_ago=30), "source_artifact": "openapi"
}

PAYMENT_DOC_V2 = {
    "service_id": "payment-service", "name": "Payment Service", "version": "v2",
    "summary": "Full-featured payment processing platform supporting charges, refunds, customers, webhooks, and payouts.",
    "description": (
        "The Payment Service v2 is the production-grade payment processing backbone of the ACME platform. "
        "It provides a comprehensive suite of financial operations including charge creation with optional capture, "
        "partial and full refunds with reason codes, customer vault management, saved payment methods, "
        "webhook event subscriptions, and automated payouts.\n\n"
        "Built on Stripe's infrastructure, v2 introduces idempotency key support on all mutating endpoints, "
        "cursor-based pagination for list endpoints, and a structured error envelope with machine-readable error codes. "
        "All monetary amounts are expressed in the smallest currency unit (e.g., 100 = $1.00 USD).\n\n"
        "Teams building new integrations MUST use v2."
    ),
    "base_url": "https://api.acme.com/payments/v2",
    "endpoints": [
        {
            "method": "POST", "path": "/charges",
            "summary": "Create a payment charge",
            "description": "Creates a new charge. Set `capture: false` to authorize without immediate capture. Supports idempotency via the `Idempotency-Key` header.",
            "authentication": "Bearer JWT token with `payments:write` scope.",
            "sample_request": json.dumps({"amount": 2999, "currency": "USD", "source": "tok_visa", "capture": True, "metadata": {"order_id": "ord_789"}}, indent=2),
            "sample_response": json.dumps({"id": "ch_v2_xyz789", "status": "succeeded", "amount": 2999, "captured": True, "livemode": True}, indent=2),
            "is_deprecated": False, "deprecation_notice": None, "parameters": [], "tags": ["Charges"],
            "usage_notes": "Rate limit: 500 req/min. Include `Idempotency-Key` header for safe retries."
        },
        {
            "method": "GET", "path": "/charges",
            "summary": "List charges with filtering",
            "description": "Returns a paginated list of charges. Uses cursor-based pagination — pass `starting_after` with a charge ID for navigation.",
            "authentication": "Bearer JWT token with `payments:read` scope.",
            "sample_request": None,
            "sample_response": json.dumps({"object": "list", "has_more": True, "data": [{"id": "ch_v2_xyz789", "amount": 2999}], "next_cursor": "ch_v2_abc123"}, indent=2),
            "is_deprecated": False, "deprecation_notice": None,
            "parameters": [{"name": "limit", "in": "query"}, {"name": "customer_id", "in": "query"}],
            "tags": ["Charges"], "usage_notes": "Default limit 10; max 100."
        },
        {
            "method": "POST", "path": "/charges/{chargeId}/capture",
            "summary": "Capture an authorized charge",
            "description": "Captures a previously authorized (uncaptured) charge. Must be called within 7 days of authorization.",
            "authentication": "Bearer JWT token with `payments:write` scope.",
            "sample_request": json.dumps({"amount": 2500}, indent=2),
            "sample_response": json.dumps({"id": "ch_v2_xyz789", "status": "succeeded", "captured": True}, indent=2),
            "is_deprecated": False, "deprecation_notice": None,
            "parameters": [{"name": "chargeId", "in": "path", "required": True}], "tags": ["Charges"]
        },
        {
            "method": "POST", "path": "/refunds",
            "summary": "Create a refund (partial or full)",
            "description": "Creates a refund for a charge. Omit `amount` for a full refund. Supports partial refunds and structured reason codes.",
            "authentication": "Bearer JWT token with `payments:write` scope.",
            "sample_request": json.dumps({"charge_id": "ch_v2_xyz789", "amount": 1000, "reason": "requested_by_customer"}, indent=2),
            "sample_response": json.dumps({"id": "re_v2_abc123", "status": "succeeded", "amount": 1000}, indent=2),
            "is_deprecated": False, "deprecation_notice": None, "parameters": [], "tags": ["Refunds"]
        },
        {
            "method": "POST", "path": "/customers",
            "summary": "Create a customer",
            "description": "Creates a customer profile in the Customer Vault. Customers can have multiple saved payment methods.",
            "authentication": "Bearer JWT token with `payments:write` scope.",
            "sample_request": json.dumps({"email": "jane@example.com", "name": "Jane Smith", "metadata": {"user_id": "usr_456"}}, indent=2),
            "sample_response": json.dumps({"id": "cus_9Z8Y7X6W", "email": "jane@example.com", "created": 1704067200}, indent=2),
            "is_deprecated": False, "deprecation_notice": None, "parameters": [], "tags": ["Customers"]
        },
        {
            "method": "GET", "path": "/customers",
            "summary": "List customers",
            "description": "Returns a paginated list of customers. Filter by email or creation date.",
            "authentication": "Bearer JWT token with `payments:read` scope.",
            "sample_request": None,
            "sample_response": json.dumps({"object": "list", "data": [{"id": "cus_9Z8Y7X6W", "email": "jane@example.com"}]}, indent=2),
            "is_deprecated": False, "deprecation_notice": None, "parameters": [], "tags": ["Customers"]
        },
        {
            "method": "GET", "path": "/customers/{customerId}/payment-methods",
            "summary": "List saved payment methods for a customer",
            "description": "Returns all saved payment methods (cards, bank accounts) attached to a customer.",
            "authentication": "Bearer JWT token with `payments:read` scope.",
            "sample_request": None,
            "sample_response": json.dumps({"data": [{"id": "pm_card_visa", "type": "card", "card": {"brand": "visa", "last4": "4242"}}]}, indent=2),
            "is_deprecated": False, "deprecation_notice": None,
            "parameters": [{"name": "customerId", "in": "path", "required": True}], "tags": ["Customers"]
        },
        {
            "method": "POST", "path": "/webhooks",
            "summary": "Register a webhook endpoint",
            "description": "Subscribes to payment events (charge.succeeded, refund.created, payout.paid). Supports up to 10 endpoints.",
            "authentication": "Bearer JWT token with `payments:admin` scope.",
            "sample_request": json.dumps({"url": "https://myapp.com/webhooks/payments", "events": ["charge.succeeded", "refund.created"]}, indent=2),
            "sample_response": json.dumps({"id": "wh_abc123", "url": "https://myapp.com/webhooks/payments", "status": "enabled"}, indent=2),
            "is_deprecated": False, "deprecation_notice": None, "parameters": [], "tags": ["Webhooks"]
        },
        {
            "method": "GET", "path": "/balance",
            "summary": "Retrieve account balance",
            "description": "Returns available and pending balance. Balance updates in real-time as charges and payouts are processed.",
            "authentication": "Bearer JWT token required.",
            "sample_request": None,
            "sample_response": json.dumps({"available": [{"amount": 150000, "currency": "USD"}], "pending": [{"amount": 5000, "currency": "USD"}]}, indent=2),
            "is_deprecated": False, "deprecation_notice": None, "parameters": [], "tags": ["Balance"]
        },
        {
            "method": "POST", "path": "/payouts",
            "summary": "Create a payout to your bank account",
            "description": "Initiates a payout to your linked bank account. Standard: 1-2 business days. Instant: same-day with 1% fee.",
            "authentication": "Bearer JWT token with `payments:admin` scope.",
            "sample_request": json.dumps({"amount": 50000, "currency": "USD", "method": "standard"}, indent=2),
            "sample_response": json.dumps({"id": "po_xyz999", "amount": 50000, "status": "pending", "arrival_date": 1704240000}, indent=2),
            "is_deprecated": False, "deprecation_notice": None, "parameters": [], "tags": ["Payouts"]
        }
    ],
    "authentication_requirements": (
        "OAuth2 Bearer tokens issued by Auth Service. Scopes: `payments:read` (GET endpoints), "
        "`payments:write` (POST/PATCH), `payments:admin` (webhooks, payouts). "
        "Include `Authorization: Bearer <token>` on all requests. "
        "Idempotency-Key header recommended for all mutating operations."
    ),
    "capabilities": [
        "Create and capture payment charges", "Partial and full refunds with reason codes",
        "Customer vault management", "Saved payment methods", "Webhook event subscriptions",
        "Automated payouts", "Cursor-based pagination", "Idempotency key support"
    ],
    "tags": ["Payments", "Charges", "Refunds", "Customers", "Webhooks", "Payouts"],
    "generated_at": ts(days_ago=2), "source_artifact": "openapi"
}

AUTH_DOC_V2 = {
    "service_id": "auth-service", "name": "Auth Service", "version": "v2",
    "summary": "Centralized identity and access management providing JWT authentication, OAuth2, and RBAC.",
    "description": (
        "The Auth Service is the identity backbone of the ACME platform. It handles user registration, "
        "authentication, session management via JWT tokens, OAuth2 social login flows, email verification, "
        "and role-based access control (RBAC). Every other service validates Bearer tokens against this service.\n\n"
        "JWT access tokens expire in 15 minutes; refresh tokens last 30 days. "
        "The public JWKS endpoint (/.well-known/jwks.json) allows other services to verify tokens locally."
    ),
    "base_url": "https://api.acme.com/auth/v2",
    "endpoints": [
        {
            "method": "POST", "path": "/login",
            "summary": "Authenticate user and receive JWT tokens",
            "description": "Validates email/password credentials and returns a short-lived access token (15min) and long-lived refresh token (30 days).",
            "authentication": "No authentication required.",
            "sample_request": json.dumps({"email": "user@acme.com", "password": "s3cur3P@ss!"}, indent=2),
            "sample_response": json.dumps({"access_token": "eyJhbG...", "refresh_token": "dGhpc...", "token_type": "Bearer", "expires_in": 900}, indent=2),
            "is_deprecated": False, "deprecation_notice": None, "parameters": [], "tags": ["Auth"]
        },
        {
            "method": "POST", "path": "/refresh",
            "summary": "Refresh an expired access token",
            "description": "Exchanges a valid refresh token for a new access token. Implements refresh token rotation — old token is invalidated.",
            "authentication": "No authentication required (refresh token in body).",
            "sample_request": json.dumps({"refresh_token": "dGhpc..."}, indent=2),
            "sample_response": json.dumps({"access_token": "eyJuZX...", "expires_in": 900}, indent=2),
            "is_deprecated": False, "deprecation_notice": None, "parameters": [], "tags": ["Auth"]
        },
        {
            "method": "GET", "path": "/me",
            "summary": "Get the authenticated user's profile",
            "description": "Returns the full user profile for the authenticated user including roles and permissions.",
            "authentication": "Bearer JWT access token required.",
            "sample_request": None,
            "sample_response": json.dumps({"id": "usr_456", "email": "user@acme.com", "roles": ["developer"], "verified": True}, indent=2),
            "is_deprecated": False, "deprecation_notice": None, "parameters": [], "tags": ["Profile"]
        },
        {
            "method": "POST", "path": "/users",
            "summary": "Register a new user account",
            "description": "Creates a new user account. Triggers a verification email. Account is unverified until email is confirmed.",
            "authentication": "No authentication required.",
            "sample_request": json.dumps({"email": "newuser@acme.com", "password": "Str0ngP@ss!", "name": "New User"}, indent=2),
            "sample_response": json.dumps({"id": "usr_789", "email": "newuser@acme.com", "verified": False, "message": "Verification email sent"}, indent=2),
            "is_deprecated": False, "deprecation_notice": None, "parameters": [], "tags": ["Users"]
        },
        {
            "method": "PUT", "path": "/users/{userId}/roles",
            "summary": "Set roles for a user (admin only)",
            "description": "Replaces a user's entire role set. Requires `auth:admin` scope. Changes take effect on next token refresh.",
            "authentication": "Bearer JWT token with `auth:admin` scope.",
            "sample_request": json.dumps({"roles": ["developer", "viewer"]}, indent=2),
            "sample_response": json.dumps({"id": "usr_456", "roles": ["developer", "viewer"], "updated_at": "2024-01-15T10:00:00Z"}, indent=2),
            "is_deprecated": False, "deprecation_notice": None,
            "parameters": [{"name": "userId", "in": "path", "required": True}], "tags": ["RBAC"]
        }
    ],
    "authentication_requirements": (
        "Most endpoints require a Bearer JWT token: `Authorization: Bearer <token>`. "
        "Tokens are obtained via POST /login or POST /refresh. "
        "Admin operations require `auth:admin` scope. "
        "Token expiry: access tokens 15 min, refresh tokens 30 days."
    ),
    "capabilities": ["JWT authentication", "OAuth2 social login", "Token refresh with rotation",
                     "Role-based access control", "Email verification", "Password reset flow"],
    "tags": ["Auth", "Users", "OAuth", "RBAC"],
    "generated_at": ts(days_ago=5), "source_artifact": "openapi"
}

ORDER_DOC_V1 = {
    "service_id": "order-service", "name": "Order Service", "version": "v1",
    "summary": "Manages the complete order lifecycle from cart to delivery tracking.",
    "description": (
        "The Order Service handles all aspects of the purchase lifecycle: shopping cart management, "
        "order placement, status tracking, cancellation, and shipping integration. "
        "It coordinates with Payment Service for charging and Inventory Service for stock reservation.\n\n"
        "Orders go through states: pending → confirmed → processing → shipped → delivered. "
        "Cancellation is only possible before the order reaches 'processing' state."
    ),
    "base_url": "https://api.acme.com/orders/v1",
    "endpoints": [
        {
            "method": "POST", "path": "/orders",
            "summary": "Place a new order",
            "description": "Creates a new order from cart contents. Automatically reserves inventory and initiates payment.",
            "authentication": "Bearer JWT token required.",
            "sample_request": json.dumps({"customer_id": "cus_9Z8Y7X6W", "items": [{"product_id": "prod_abc", "quantity": 2}], "payment_method_id": "pm_card_visa"}, indent=2),
            "sample_response": json.dumps({"id": "ord_789", "status": "confirmed", "total": 5998, "estimated_delivery": "2024-01-18"}, indent=2),
            "is_deprecated": False, "deprecation_notice": None, "parameters": [], "tags": ["Orders"]
        },
        {
            "method": "GET", "path": "/orders/{orderId}/tracking",
            "summary": "Get shipping tracking info",
            "description": "Returns real-time shipping tracking data including carrier, tracking number, and estimated delivery.",
            "authentication": "Bearer JWT token required.",
            "sample_request": None,
            "sample_response": json.dumps({"carrier": "FedEx", "tracking_number": "794644774000", "status": "In Transit", "estimated_delivery": "2024-01-18"}, indent=2),
            "is_deprecated": False, "deprecation_notice": None,
            "parameters": [{"name": "orderId", "in": "path", "required": True}], "tags": ["Shipping"]
        }
    ],
    "authentication_requirements": "Bearer JWT token required for all endpoints.",
    "capabilities": ["Order placement and lifecycle", "Shopping cart management", "Shipping tracking", "Order cancellation"],
    "tags": ["Orders", "Cart", "Shipping"],
    "generated_at": ts(days_ago=10), "source_artifact": "openapi"
}

NOTIFICATION_DOC_V1 = {
    "service_id": "notification-service", "name": "Notification Service", "version": "v1",
    "summary": "Multi-channel notification delivery supporting email, SMS, push, and in-app notifications.",
    "description": (
        "The Notification Service provides a unified API for sending communications across all channels. "
        "Template-based messaging ensures consistent branding. "
        "Supports bulk sending, user preferences, and global unsubscribe compliance."
    ),
    "base_url": "https://api.acme.com/notifications/v1",
    "endpoints": [
        {
            "method": "POST", "path": "/send",
            "summary": "Send a notification",
            "description": "Sends a single notification via the specified channel using a template.",
            "authentication": "API Key in X-API-Key header.",
            "sample_request": json.dumps({"recipient_id": "usr_456", "channel": "email", "template_id": "order_confirmed", "variables": {"order_id": "ord_789"}, "priority": "high"}, indent=2),
            "sample_response": json.dumps({"notification_id": "notif_xyz", "status": "queued", "estimated_delivery": "2s"}, indent=2),
            "is_deprecated": False, "deprecation_notice": None, "parameters": [], "tags": ["Notifications"]
        },
        {
            "method": "POST", "path": "/email/send",
            "summary": "Send email (legacy — deprecated)",
            "description": "Legacy email sending endpoint. Use POST /send with channel=email instead.",
            "authentication": "API Key in X-API-Key header.",
            "sample_request": None, "sample_response": None,
            "is_deprecated": True,
            "deprecation_notice": "Deprecated. Use POST /send with channel='email'. Will be removed in v2.",
            "parameters": [], "tags": ["Legacy"]
        }
    ],
    "authentication_requirements": "API Key authentication via X-API-Key header. Keys are scoped per service.",
    "capabilities": ["Email, SMS, push, in-app delivery", "Template-based messaging", "Bulk sending (up to 1000/batch)", "User preference management", "Global unsubscribe"],
    "tags": ["Notifications", "Email", "SMS", "Push"],
    "generated_at": ts(days_ago=7), "source_artifact": "openapi"
}

INVENTORY_DOC_V1 = {
    "service_id": "inventory-service", "name": "Inventory Service", "version": "v1",
    "summary": "Real-time inventory tracking and warehouse management with stock reservation support.",
    "description": (
        "The Inventory Service maintains accurate stock levels across all warehouses. "
        "It provides real-time stock queries, multi-warehouse management, stock reservations for in-flight orders, "
        "and low-stock alerting. Integrates with Order Service for automatic reservation on order placement."
    ),
    "base_url": "https://api.acme.com/inventory/v1",
    "endpoints": [
        {
            "method": "PATCH", "path": "/products/{productId}/stock",
            "summary": "Adjust stock level",
            "description": "Adjusts stock by a delta amount (positive to add, negative to remove). Used by warehouse operations.",
            "authentication": "Bearer JWT token with `inventory:write` scope.",
            "sample_request": json.dumps({"delta": -5, "reason": "sale", "warehouse_id": "wh_main"}, indent=2),
            "sample_response": json.dumps({"product_id": "prod_abc", "stock_level": 45, "warehouse": "wh_main"}, indent=2),
            "is_deprecated": False, "deprecation_notice": None,
            "parameters": [{"name": "productId", "in": "path", "required": True}], "tags": ["Stock"]
        },
        {
            "method": "POST", "path": "/reservations",
            "summary": "Reserve stock for an order",
            "description": "Temporarily reserves stock to prevent overselling. Reservation expires in 15 minutes if not confirmed.",
            "authentication": "Bearer JWT token with `inventory:write` scope.",
            "sample_request": json.dumps({"order_id": "ord_789", "items": [{"product_id": "prod_abc", "quantity": 2}]}, indent=2),
            "sample_response": json.dumps({"reservation_id": "res_xyz", "expires_at": "2024-01-15T10:15:00Z", "items_reserved": [{"product_id": "prod_abc", "quantity": 2}]}, indent=2),
            "is_deprecated": False, "deprecation_notice": None, "parameters": [], "tags": ["Reservations"]
        }
    ],
    "authentication_requirements": "Bearer JWT token required. Write operations need `inventory:write` scope.",
    "capabilities": ["Real-time stock tracking", "Multi-warehouse management", "Stock reservations", "Low-stock alerts", "Product catalog"],
    "tags": ["Products", "Stock", "Warehouses", "Reservations"],
    "generated_at": ts(days_ago=3), "source_artifact": "openapi"
}


# ── Changelog data (seeded into SQLite) ───────────────────────────────────────

PAYMENT_CHANGELOG = {
    "service_id": "payment-service", "from_version": "v1", "to_version": "v2",
    "summary": (
        "Major upgrade: v2 adds customer vault, webhooks, payouts, partial refunds, and idempotency support. "
        "2 breaking changes: charge endpoint renamed from /charge to /charges, and legacy refund path removed."
    ),
    "total_changes": 14, "breaking_changes_count": 2,
    "changes": [
        {"change_type": "modified", "category": "endpoints", "path": "POST /charge → POST /charges",
         "description": "Charge creation endpoint renamed from /charge to /charges for REST consistency.", "breaking": True,
         "details": "Update all clients calling POST /charge to use POST /charges."},
        {"change_type": "removed", "category": "endpoints", "path": "POST /refunds/{chargeId}",
         "description": "Legacy path-param refund endpoint removed. Replaced by POST /refunds with body parameters.", "breaking": True,
         "details": "Migrate to POST /refunds with {charge_id, amount, reason} in request body."},
        {"change_type": "added", "category": "endpoints", "path": "POST /charges/{chargeId}/capture",
         "description": "New endpoint to capture previously authorized charges.", "breaking": False, "details": None},
        {"change_type": "added", "category": "endpoints", "path": "GET /charges",
         "description": "New list charges endpoint with filtering and cursor-based pagination.", "breaking": False, "details": None},
        {"change_type": "added", "category": "endpoints", "path": "POST /customers",
         "description": "New Customer Vault for saving payment methods.", "breaking": False, "details": None},
        {"change_type": "added", "category": "endpoints", "path": "POST /webhooks",
         "description": "New webhook registration for real-time payment events.", "breaking": False, "details": None},
        {"change_type": "added", "category": "endpoints", "path": "POST /payouts",
         "description": "On-demand payout creation to linked bank accounts.", "breaking": False, "details": None},
        {"change_type": "added", "category": "security", "path": "Idempotency-Key header",
         "description": "All mutating endpoints now support Idempotency-Key for safe retry.", "breaking": False, "details": None},
        {"change_type": "modified", "category": "authentication", "path": "OAuth2 scopes",
         "description": "Introduced granular scopes: payments:read, payments:write, payments:admin.", "breaking": False, "details": None},
        {"change_type": "added", "category": "pagination", "path": "All list endpoints",
         "description": "All list endpoints now use cursor-based pagination.", "breaking": False, "details": None},
    ]
}


# ── Gap report data (seeded into SQLite) ──────────────────────────────────────

PAYMENT_GAP_REPORT = {
    "service_id": "payment-service", "version": "v2",
    "documentation_coverage_pct": 73.0, "severity": "medium",
    "undocumented_endpoints": [
        {"method": "DELETE", "path": "/customers/{customerId}", "hit_count": 234,
         "note": "Endpoint observed in traffic but not in OpenAPI spec or docs"},
        {"method": "GET", "path": "/charges/{chargeId}/timeline", "hit_count": 891,
         "note": "High-traffic endpoint with no documentation"},
        {"method": "POST", "path": "/disputes/{disputeId}/evidence", "hit_count": 56,
         "note": "Dispute management endpoint entirely undocumented"},
        {"method": "GET", "path": "/reports/revenue", "hit_count": 127,
         "note": "Revenue reporting endpoint used by finance team — no docs"},
        {"method": "PUT", "path": "/webhooks/{webhookId}", "hit_count": 43,
         "note": "Webhook update endpoint not documented"}
    ],
    "missing_doc_endpoints": [
        "PATCH /charges/{chargeId} — no description of which fields are mutable",
        "GET /customers — no filter parameters documented",
        "GET /payouts — missing pagination and date filter documentation",
    ],
    "recommendations": (
        "Priority 1: Document GET /charges/{chargeId}/timeline — 891 hits/day, critical for support workflows.\n"
        "Priority 2: Document POST /disputes/{disputeId}/evidence — compliance risk.\n"
        "Priority 3: Register GET /reports/revenue — shadow API used by Finance team."
    )
}

AUTH_GAP_REPORT = {
    "service_id": "auth-service", "version": "v2",
    "documentation_coverage_pct": 91.0, "severity": "low",
    "undocumented_endpoints": [
        {"method": "GET", "path": "/.well-known/jwks.json", "hit_count": 15420,
         "note": "JWKS public key endpoint — highest traffic, no docs"},
        {"method": "POST", "path": "/users/{userId}/disable", "hit_count": 12,
         "note": "Admin user disable endpoint used by ops team"}
    ],
    "missing_doc_endpoints": [
        "DELETE /users/{userId} — no documentation on data retention policy",
        "GET /users — admin endpoint with no documented query parameters"
    ],
    "recommendations": (
        "Priority 1: Document GET /.well-known/jwks.json — 15,420 hits/day, every service calls it to validate JWTs.\n"
        "Priority 2: Document admin endpoints with clear access control requirements."
    )
}


# ── Traffic data (seeded into APIPlatform) ────────────────────────────────────

PAYMENT_TRAFFIC = [
    {"method": "POST", "path": "/charges", "hit_count": 8920},
    {"method": "GET", "path": "/charges", "hit_count": 3210},
    {"method": "GET", "path": "/charges/{chargeId}", "hit_count": 12400},
    {"method": "POST", "path": "/charges/{chargeId}/capture", "hit_count": 1890},
    {"method": "POST", "path": "/refunds", "hit_count": 2340},
    {"method": "GET", "path": "/balance", "hit_count": 890},
    {"method": "POST", "path": "/customers", "hit_count": 1200},
    {"method": "GET", "path": "/customers", "hit_count": 780},
    {"method": "DELETE", "path": "/customers/{customerId}", "hit_count": 234},   # undocumented
    {"method": "GET", "path": "/charges/{chargeId}/timeline", "hit_count": 891}, # undocumented high-traffic
    {"method": "POST", "path": "/disputes/{disputeId}/evidence", "hit_count": 56},# undocumented
    {"method": "GET", "path": "/reports/revenue", "hit_count": 127},              # shadow API
    {"method": "PUT", "path": "/webhooks/{webhookId}", "hit_count": 43},          # undocumented
    {"method": "POST", "path": "/webhooks", "hit_count": 320},
    {"method": "GET", "path": "/payouts", "hit_count": 450},
]

AUTH_TRAFFIC = [
    {"method": "POST", "path": "/login", "hit_count": 45200},
    {"method": "POST", "path": "/refresh", "hit_count": 89300},
    {"method": "GET", "path": "/me", "hit_count": 156000},
    {"method": "POST", "path": "/logout", "hit_count": 12000},
    {"method": "GET", "path": "/.well-known/jwks.json", "hit_count": 15420},  # undocumented
    {"method": "POST", "path": "/users", "hit_count": 890},
    {"method": "GET", "path": "/users/{userId}/roles", "hit_count": 2300},
    {"method": "POST", "path": "/users/{userId}/disable", "hit_count": 12},   # undocumented admin
    {"method": "GET", "path": "/oauth/authorize", "hit_count": 3400},
]


# ── Seed functions ────────────────────────────────────────────────────────────

async def seed_api_platform(client: httpx.AsyncClient):
    """POST registry data (services, specs, traffic) to APIPlatform API."""
    print("\n[1/2] Seeding APIPlatform API...")

    services = [
        {"service_id": "payment-service",      "name": "Payment Service",      "version": "v2",
         "description": "Handles all payment processing for the ACME platform",
         "base_url": "https://api.acme.com/payments/v2", "tags": ["Payments", "Finance", "Critical"]},
        {"service_id": "auth-service",         "name": "Auth Service",         "version": "v2",
         "description": "Identity and access management",
         "base_url": "https://api.acme.com/auth/v2", "tags": ["Auth", "Security", "Critical"]},
        {"service_id": "order-service",        "name": "Order Service",        "version": "v1",
         "description": "Order lifecycle management",
         "base_url": "https://api.acme.com/orders/v1", "tags": ["Orders", "Commerce"]},
        {"service_id": "notification-service", "name": "Notification Service", "version": "v1",
         "description": "Multi-channel notification delivery (email, SMS, push)",
         "base_url": "https://api.acme.com/notifications/v1", "tags": ["Notifications", "Messaging"]},
        {"service_id": "inventory-service",    "name": "Inventory Service",    "version": "v1",
         "description": "Real-time inventory tracking and warehouse management",
         "base_url": "https://api.acme.com/inventory/v1", "tags": ["Inventory", "Warehouse"]},
    ]

    for svc in services:
        r = await client.post(f"{API_PLATFORM_URL}/services", json=svc)
        r.raise_for_status()
        print(f"  Registered: {svc['service_id']} v{svc['version']}")

    # Upload specs
    specs = [
        ("payment-service", "v1", PAYMENT_SPEC_V1),
        ("payment-service", "v2", PAYMENT_SPEC_V2),
        ("auth-service",    "v2", AUTH_SPEC_V2),
        ("order-service",   "v1", ORDER_SPEC_V1),
        ("notification-service", "v1", NOTIFICATION_SPEC_V1),
        ("inventory-service",    "v1", INVENTORY_SPEC_V1),
    ]
    for sid, ver, content in specs:
        r = await client.post(f"{API_PLATFORM_URL}/services/{sid}/spec",
                              json={"version": ver, "content": content, "artifact_type": "openapi"})
        r.raise_for_status()
        print(f"  Spec uploaded: {sid} v{ver}")

    # Upload traffic
    r = await client.post(f"{API_PLATFORM_URL}/services/payment-service/traffic", json=PAYMENT_TRAFFIC)
    r.raise_for_status()
    print(f"  Traffic loaded: payment-service ({len(PAYMENT_TRAFFIC)} endpoints)")

    r = await client.post(f"{API_PLATFORM_URL}/services/auth-service/traffic", json=AUTH_TRAFFIC)
    r.raise_for_status()
    print(f"  Traffic loaded: auth-service ({len(AUTH_TRAFFIC)} endpoints)")

    print("  APIPlatform seeding complete.")


async def seed_sqlite():
    """Seed SQLite with pre-generated AI docs, changelogs, and gap reports."""
    print("\n[2/2] Seeding SQLite (AI-generated content)...")

    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.executescript("""
            CREATE TABLE IF NOT EXISTS service_docs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id TEXT NOT NULL, version TEXT NOT NULL,
                doc_json TEXT NOT NULL, generated_at TEXT NOT NULL,
                UNIQUE(service_id, version)
            );
            CREATE TABLE IF NOT EXISTS change_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id TEXT NOT NULL, from_version TEXT NOT NULL,
                to_version TEXT NOT NULL, changelog_json TEXT NOT NULL,
                generated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS gap_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id TEXT NOT NULL, report_json TEXT NOT NULL,
                generated_at TEXT NOT NULL
            );
        """)
        await conn.commit()

        docs = [
            ("payment-service", "v1", json.dumps(PAYMENT_DOC_V1), ts(30)),
            ("payment-service", "v2", json.dumps(PAYMENT_DOC_V2), ts(2)),
            ("auth-service",    "v2", json.dumps(AUTH_DOC_V2),    ts(5)),
            ("order-service",   "v1", json.dumps(ORDER_DOC_V1),   ts(10)),
            ("notification-service", "v1", json.dumps(NOTIFICATION_DOC_V1), ts(7)),
            ("inventory-service",    "v1", json.dumps(INVENTORY_DOC_V1),    ts(3)),
        ]
        for sid, ver, doc_json, gat in docs:
            await conn.execute("""
                INSERT INTO service_docs (service_id, version, doc_json, generated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(service_id, version) DO UPDATE SET
                    doc_json=excluded.doc_json, generated_at=excluded.generated_at
            """, (sid, ver, doc_json, gat))
            print(f"  Doc seeded: {sid} v{ver}")

        await conn.execute("""
            INSERT INTO change_logs (service_id, from_version, to_version, changelog_json, generated_at)
            VALUES (?, ?, ?, ?, ?)
        """, ("payment-service", "v1", "v2", json.dumps(PAYMENT_CHANGELOG), ts(2)))
        print("  Changelog seeded: payment-service v1->v2")

        await conn.execute("""
            INSERT INTO gap_reports (service_id, report_json, generated_at)
            VALUES (?, ?, ?)
        """, ("payment-service", json.dumps(PAYMENT_GAP_REPORT), ts(1)))
        await conn.execute("""
            INSERT INTO gap_reports (service_id, report_json, generated_at)
            VALUES (?, ?, ?)
        """, ("auth-service", json.dumps(AUTH_GAP_REPORT), ts(1)))
        print("  Gap reports seeded: payment-service, auth-service")

        await conn.commit()

    print("  SQLite seeding complete.")


async def seed():
    print("=" * 60)
    print("ServiceAssist Seed Script")
    print(f"  APIPlatform: {API_PLATFORM_URL}")
    print(f"  SQLite DB:   {DB_PATH}")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Check APIPlatform is running
        try:
            r = await client.get(f"{API_PLATFORM_URL}/health")
            r.raise_for_status()
            print(f"\nAPIPlatform is healthy: {r.json()}")
        except Exception as e:
            print(f"\nERROR: Cannot reach APIPlatform at {API_PLATFORM_URL}")
            print(f"  Start it first: python run_api_platform.py")
            print(f"  Error: {e}")
            return

        await seed_api_platform(client)

    await seed_sqlite()

    print("\n" + "=" * 60)
    print("[OK] Seed complete!")
    print("  Services in APIPlatform: payment-service (v1+v2), auth-service (v2),")
    print("                           order-service (v1), notification-service (v1), inventory-service (v1)")
    print("  AI docs in SQLite: all 6 services pre-generated")
    print("  Changelogs: payment-service v1->v2 (10 changes, 2 breaking)")
    print("  Gap reports: payment-service (73% coverage), auth-service (91% coverage)")
    print("  Traffic in APIPlatform: payment-service (15 endpoints), auth-service (9 endpoints)")
    print()
    print("  Start servers:")
    print("    python run_api_platform.py   # port 8001")
    print("    python run.py                # port 8000")
    print("  Then open: http://localhost:8000")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(seed())
