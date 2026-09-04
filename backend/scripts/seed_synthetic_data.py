"""CLI Script to seed synthetic merchant dataset.
Usage: python scripts/seed_synthetic_data.py --customers 1000 --cases 500 --seed 20260902
"""
import argparse
import sys
import os

# Add backend directory to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(current_dir) if "scripts" in current_dir else current_dir
sys.path.insert(0, backend_dir)

from app.db import init_db, SessionLocal
from app.simulation.generator import generate_synthetic_dataset


def main():
    parser = argparse.ArgumentParser(description="Seed RecoverX synthetic merchant dataset")
    parser.add_argument("--customers", type=int, default=1000, help="Number of synthetic customers to generate")
    parser.add_argument("--cases", type=int, default=500, help="Number of synthetic recovery cases to generate")
    parser.add_argument("--seed", type=int, default=20260902, help="Deterministic random seed")

    args = parser.parse_args()

    print(f"Initializing RecoverX database...")
    init_db()

    session = SessionLocal()
    try:
        print(f"Generating synthetic dataset: {args.customers} customers, {args.cases} cases (seed={args.seed})...")
        res = generate_synthetic_dataset(
            session=session,
            customer_count=args.customers,
            case_count=args.cases,
            seed=args.seed,
        )
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
        print(f"[OK] Synthetic dataset successfully generated!")
        print(f"  - Customers: {res['customers']}")
        print(f"  - Cases: {res['cases']}")
        print(f"  - Seed: {res['seed']}")
    except Exception as e:
        print(f"Error seeding dataset: {e}")
        session.rollback()
        raise e
    finally:
        session.close()


if __name__ == "__main__":
    main()
