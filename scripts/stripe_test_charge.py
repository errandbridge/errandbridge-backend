#!/usr/bin/env python3
"""Create a Stripe test-mode charge for cron/monitoring verification.

Usage:
  python scripts/stripe_test_charge.py --amount 1.00 --currency usd

Requires:
  STRIPE_SECRET_KEY in environment (.env supported).
"""

from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal, InvalidOperation

from dotenv import load_dotenv
import stripe


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a Stripe test-mode $1 charge.")
    parser.add_argument(
        "--amount", default="1.00", help="Amount in dollars (default: 1.00)"
    )
    parser.add_argument(
        "--currency", default="usd", help="Currency code (default: usd)"
    )
    parser.add_argument(
        "--payment-method", default="pm_card_visa", help="Stripe test payment method"
    )
    parser.add_argument("--customer-id", default="", help="Optional Stripe customer ID")
    parser.add_argument(
        "--description", default="ErrandBridge test charge", help="Charge description"
    )
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="Allow a live-mode charge (requires a real payment method ID).",
    )
    parser.add_argument(
        "--live-payment-method-id",
        default="",
        help="Live-mode payment method ID to charge (e.g., pm_...).",
    )
    return parser.parse_args()


def amount_to_cents(amount_str: str) -> int:
    try:
        amount = Decimal(amount_str)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid amount '{amount_str}'.") from exc
    if amount <= 0:
        raise ValueError("Amount must be positive.")
    return int((amount * 100).to_integral_value())


def main() -> int:
    load_dotenv()
    args = parse_args()

    stripe_key = os.getenv("STRIPE_SECRET_KEY")
    if not stripe_key:
        print(
            "ERROR: STRIPE_SECRET_KEY is not set. Add it to your .env before running."
        )
        return 1

    stripe.api_key = stripe_key

    is_live_mode = stripe_key.startswith("sk_live")
    if is_live_mode and not args.allow_live:
        print(
            "ERROR: Live-mode Stripe key detected. Use a test key or pass --allow-live with a real payment method ID."
        )
        return 1
    if is_live_mode and not args.live_payment_method_id:
        print(
            "ERROR: Live-mode charge requested but no --live-payment-method-id was provided."
        )
        return 1

    payment_method = (
        args.live_payment_method_id if is_live_mode else args.payment_method
    )

    try:
        amount_cents = amount_to_cents(args.amount)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1

    create_kwargs = {
        "amount": amount_cents,
        "currency": args.currency,
        "payment_method": payment_method,
        "confirm": True,
        "description": args.description,
    }
    if args.customer_id:
        create_kwargs["customer"] = args.customer_id

    try:
        intent = stripe.PaymentIntent.create(**create_kwargs)
    except Exception as exc:  # pragma: no cover - Stripe errors are external
        print(f"ERROR: Stripe charge failed: {exc}")
        return 1

    print("Stripe test charge successful")
    print(f"PaymentIntent: {intent.id}")
    print(f"Status: {intent.status}")
    print(f"Amount: {intent.amount} {intent.currency}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
