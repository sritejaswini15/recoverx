"""500-Case Batch Evaluation CLI Script for RecoverX.
Runs the evaluation suite and displays comprehensive recovery and safety metrics.
Usage: python scripts/run_batch_evaluation.py --seed 20260902
"""
import argparse
import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(current_dir) if "scripts" in current_dir else current_dir
sys.path.insert(0, backend_dir)

from app.db import SessionLocal
from app.services.evaluation_service import EvaluationService


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    session = SessionLocal()
    try:
        print("=" * 60)
        print("  RECOVERX 500-CASE BATCH EVALUATION BENCHMARK")
        print("=" * 60)
        
        results = EvaluationService.run_evaluation(session)
        if "error" in results:
            print(f"Error: {results['error']}")
            return

        print(f"Cases Processed:             {results['cases_processed']:,}")
        print(f"Revenue At Risk:             INR {results['revenue_at_risk']:,}")
        print(f"Revenue Targeted:            INR {results['revenue_targeted']:,}")
        print(f"Revenue Recovered:           INR {results['revenue_recovered']:,}")
        print(f"Recovery Rate:               {results['recovery_rate'] * 100:.1f}%")
        print(f"Average Recovery Probability: {results['average_recovery_probability'] * 100:.1f}%")
        print(f"Average AI Confidence:       {results['average_ai_confidence'] * 100:.1f}%")
        print(f"Successful Recoveries:       {results['successful_recoveries']:,}")
        print(f"Escalations:                 {results['escalations']:,}")
        print(f"False Escalations:           {results['false_escalations']}")
        print(f"Policy Violations:           {results['policy_violations']}")
        print(f"Invalid AI Decisions:        {results['invalid_ai_decisions']}")
        print(f"Action Failures:             {results['action_failures']}")
        print(f"Average Recovery Time:       {results['average_recovery_time_hours']} hours")
        print("-" * 60)
        print(f"EVALUATION STATUS:           [{results['evaluation_status']}]")
        print("=" * 60)
    finally:
        session.close()


if __name__ == "__main__":
    main()
