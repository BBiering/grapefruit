"""
One-time migration script to backfill data from legacy tables to new schema.

Migrates:
1. winners → step_change_history (tier='major')
2. winner_catalysts → step_change_catalysts

Run once after deploying migration 0007_universe_wide_data.sql
"""
import logging
from grapefruit import storage

log = logging.getLogger(__name__)


def migrate_winners_to_step_changes() -> int:
    """Migrate all winners to step_change_history with tier='major'."""
    log.info("Starting migration: winners → step_change_history")

    # Load all winners
    with storage._cur(row_factory=storage.dict_row) as cur:
        cur.execute("""
            SELECT id, symbol, start_ts, end_ts, days_to_peak,
                   trough_price, peak_price, multiplier,
                   post_peak_retention, breakout_ratio,
                   market_cap_usd_at_peak, status
            FROM winners
            ORDER BY id
        """)
        winners = cur.fetchall()

    log.info(f"Found {len(winners)} winners to migrate")

    # Map old winner_id → new step_change_id for catalyst migration
    id_mapping = {}
    migrated = 0

    for w in winners:
        # Insert into step_change_history
        step_change_row = {
            "symbol": w["symbol"],
            "start_ts": w["start_ts"],
            "end_ts": w["end_ts"],
            "days_to_peak": w["days_to_peak"],
            "trough_price": w["trough_price"],
            "peak_price": w["peak_price"],
            "multiplier": w["multiplier"],
            "post_peak_retention": w.get("post_peak_retention"),
            "breakout_ratio": w.get("breakout_ratio"),
            "market_cap_usd_at_peak": w.get("market_cap_usd_at_peak"),
            "status": w["status"],
            "tier": "major",  # All existing winners are 5x+ = major
        }

        new_id = storage.upsert_step_change(step_change_row)
        id_mapping[w["id"]] = new_id
        migrated += 1

        if migrated % 100 == 0:
            log.info(f"Migrated {migrated}/{len(winners)} winners")

    log.info(f"✓ Migrated {migrated} winners to step_change_history")
    return migrated, id_mapping


def migrate_winner_catalysts(id_mapping: dict[int, int]) -> int:
    """Migrate winner_catalysts to step_change_catalysts using id mapping."""
    log.info("Starting migration: winner_catalysts → step_change_catalysts")

    # Load all winner catalysts
    with storage._cur(row_factory=storage.dict_row) as cur:
        cur.execute("""
            SELECT winner_id, headline, summary, spike_explanation,
                   was_foreseeable, foreseeable_evidence,
                   perplexity_citations, fetched_at
            FROM winner_catalysts
            ORDER BY winner_id
        """)
        catalysts = cur.fetchall()

    log.info(f"Found {len(catalysts)} winner catalysts to migrate")

    migrated = 0
    skipped = 0

    for c in catalysts:
        old_winner_id = c["winner_id"]

        # Look up new step_change_id
        new_step_change_id = id_mapping.get(old_winner_id)
        if not new_step_change_id:
            log.warning(f"Skipping catalyst for winner_id={old_winner_id} (no mapping found)")
            skipped += 1
            continue

        catalyst_row = {
            "step_change_id": new_step_change_id,
            "headline": c.get("headline"),
            "summary": c.get("summary"),
            "spike_explanation": c.get("spike_explanation"),
            "was_foreseeable": c.get("was_foreseeable"),
            "foreseeable_evidence": c.get("foreseeable_evidence"),
            "perplexity_citations": c.get("perplexity_citations"),
            "model": "sonar-pro",  # Default for historical data
        }

        storage.upsert_step_change_catalyst(catalyst_row)
        migrated += 1

        if migrated % 50 == 0:
            log.info(f"Migrated {migrated}/{len(catalysts)} catalysts")

    log.info(f"✓ Migrated {migrated} catalysts to step_change_catalysts (skipped {skipped})")
    return migrated


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log.info("="*60)
    log.info("Starting historical data migration")
    log.info("="*60)

    # Initialize DB to ensure new tables exist
    storage.init_db()

    # Step 1: Migrate winners
    winners_migrated, id_mapping = migrate_winners_to_step_changes()

    # Step 2: Migrate winner catalysts
    catalysts_migrated = migrate_winner_catalysts(id_mapping)

    log.info("="*60)
    log.info("Migration complete!")
    log.info(f"  Winners migrated: {winners_migrated}")
    log.info(f"  Catalysts migrated: {catalysts_migrated}")
    log.info("="*60)
    log.info("")
    log.info("Next steps:")
    log.info("1. Verify data: Check step_change_history and step_change_catalysts tables")
    log.info("2. Run detect_step_changes.py to backfill moderate/minor tier events")
    log.info("3. Update frontend to query new tables")
    log.info("4. After validation, drop legacy tables: winners, winner_catalysts")


if __name__ == "__main__":
    main()
