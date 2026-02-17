"""
Pickr AI Email Sales Rep — Main Entry Point (v2.1)

Usage:
    # Start the web dashboard + API server:
    python main.py serve

    # Process all queued jobs (scrape, classify, leverage, email):
    python main.py process

    # Import leads from CSV:
    python main.py import leads.csv

    # Seed database with rules, brands, and objection templates:
    python main.py seed

    # Check pipeline stats:
    python main.py stats

    # Handle a reply (for testing):
    python main.py reply <lead_id> "reply text"

    # Initialize database only:
    python main.py init
"""
import sys
import csv
import json
import logging
import os
import uvicorn
from pathlib import Path
from pickr.config import APP_HOST, APP_PORT, DEBUG, DATA_DIR, SCHEMA_VERSION
from pickr.models import (
    init_db, SessionLocal, Lead, LeadCreateRequest,
    RulesLeverageMatrix, Brand, ObjectionsKB,
)
from pickr.pipeline import PickrPipeline

# Setup logging - write to stdout instead of stderr for Railway
import sys
logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("pickr")


def seed_database(db):
    """Seed the database with leverage rules, brands, and objection templates."""
    # Seed leverage rules
    rules_file = DATA_DIR / "leverage_rules.json"
    if rules_file.exists():
        existing = db.query(RulesLeverageMatrix).count()
        if existing == 0:
            rules = json.loads(rules_file.read_text())
            for r in rules:
                db.add(RulesLeverageMatrix(**r))
            db.commit()
            logger.info(f"Seeded {len(rules)} leverage rules.")
        else:
            logger.info(f"Leverage rules already seeded ({existing} rules).")

    # Seed brands
    brands_file = DATA_DIR / "brands.json"
    if brands_file.exists():
        existing = db.query(Brand).count()
        if existing == 0:
            brands = json.loads(brands_file.read_text())
            for b in brands:
                db.add(Brand(**b))
            db.commit()
            logger.info(f"Seeded {len(brands)} brands.")
        else:
            logger.info(f"Brands already seeded ({existing} brands).")

    # Seed objection templates
    objections_file = DATA_DIR / "objections_kb.json"
    if objections_file.exists():
        existing = db.query(ObjectionsKB).count()
        if existing == 0:
            objections = json.loads(objections_file.read_text())
            for o in objections:
                db.add(ObjectionsKB(**o))
            db.commit()
            logger.info(f"Seeded {len(objections)} objection templates.")
        else:
            logger.info(f"Objections already seeded ({existing} templates).")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    command = sys.argv[1].lower()
    pipeline = PickrPipeline()

    if command == "serve":
        # Start the web server
        port = int(os.getenv("PORT", APP_PORT))
        pipeline.initialize()

        # Auto-seed on first startup
        db = SessionLocal()
        try:
            seed_database(db)
        finally:
            db.close()

        print(f"\n  Pickr AI v2 Dashboard running at http://localhost:{port}")
        print(f"  Schema: {SCHEMA_VERSION}\n")
        uvicorn.run(
            "pickr.web.dashboard:app",
            host=APP_HOST,
            port=port,
            reload=DEBUG,
        )

    elif command == "init":
        # Initialize the database
        pipeline.initialize()
        db = SessionLocal()
        try:
            seed_database(db)
        finally:
            db.close()
        print(f"Database initialized and seeded. Schema: {SCHEMA_VERSION}")

    elif command == "seed":
        # Seed database with rules, brands, and objection templates
        pipeline.initialize()
        db = SessionLocal()
        try:
            seed_database(db)
        finally:
            db.close()
        print("Database seeded successfully.")

    elif command == "process":
        # Process all queued jobs
        pipeline.initialize()
        db = SessionLocal()
        try:
            results = pipeline.process_queued_jobs(db)
            print(f"Processing complete: {results}")
        finally:
            db.close()

    elif command == "import":
        # Import leads from CSV
        if len(sys.argv) < 3:
            print("Usage: python main.py import <file.csv>")
            return

        csv_path = sys.argv[2]
        pipeline.initialize()
        db = SessionLocal()
        try:
            results = {"created": 0, "skipped": 0, "errors": 0}
            with open(csv_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        req = LeadCreateRequest(
                            company_name=row.get("company_name", row.get("company", "")),
                            website_url=row.get("website_url", row.get("website", "")),
                            contact_email=row.get("contact_email", row.get("email", "")),
                            channel=row.get("channel"),
                            niche=row.get("niche"),
                            location=row.get("location"),
                        )
                        result = pipeline.create_lead(db, req)
                        if result.get("suppressed") or result.get("dedupe"):
                            results["skipped"] += 1
                        else:
                            results["created"] += 1
                    except Exception as e:
                        logger.error(f"Row import error: {e}")
                        results["errors"] += 1

            print(f"Import from {csv_path}: {results}")
        finally:
            db.close()

    elif command == "stats":
        # Show pipeline stats
        pipeline.initialize()
        db = SessionLocal()
        try:
            stats = pipeline.get_stats(db)
            print("\n  Pickr AI v2 Pipeline Stats")
            print("  " + "=" * 45)
            for key, value in stats.items():
                label = key.replace("_", " ").title()
                print(f"  {label:.<35} {value}")
            print()
        finally:
            db.close()

    elif command == "reply":
        # Handle a reply (for testing)
        if len(sys.argv) < 4:
            print('Usage: python main.py reply <lead_id> "reply text"')
            return

        lead_id = sys.argv[2]
        reply_text = sys.argv[3]
        pipeline.initialize()
        db = SessionLocal()
        try:
            result = pipeline.handle_reply(db, lead_id, reply_text)
            print(f"\nResult: {json.dumps(result, indent=2, default=str)}")
        finally:
            db.close()

    else:
        print(f"Unknown command: {command}")
        print(__doc__)


if __name__ == "__main__":
    main()
