"""
Weekly: Compute quality/financial metrics for ALL universe stocks.

Replaces refresh_watchlist's limited scope (top 40 stocks) with universe-wide coverage.

Steps:
1. Load all universe symbols from assets table
2. Fetch fundamentals for ALL symbols (rate-limited: 900/min)
3. Calculate quality_score + insider_score for each
4. Store in company_metrics table
5. Fall back to neutral scores (50) when data unavailable

Runtime: ~2-3 minutes for 1,876 stocks
"""
from __future__ import annotations

import logging
import time
from datetime import date

from grapefruit import eodhd_client, screening, storage

log = logging.getLogger(__name__)

# EODHD rate limit: 900 requests/minute (free tier: 100k/month)
RATE_LIMIT_PER_MINUTE = 900
BATCH_SIZE = 50  # Log progress every N symbols


def run(batch_size: int = 100) -> int:
    """Fetch fundamentals and compute metrics for all universe stocks.

    Writes to database incrementally in batches to fail fast and avoid data loss.

    Args:
        batch_size: Number of stocks to process before writing to DB (default 100)

    Returns:
        Total number of metrics stored
    """
    assets = storage.load_assets_map()
    if not assets:
        log.warning("No symbols in `assets`; run refresh_universe first")
        return 0

    symbols = list(assets.keys())
    log.info(f"Computing metrics for {len(symbols)} universe stocks (batch size: {batch_size})")

    metrics_batch = []
    total_stored = 0
    fetched_count = 0
    failed_count = 0
    start_time = time.time()

    for i, symbol in enumerate(symbols, start=1):
        # Rate limiting: ~900 calls/min = 15 calls/sec
        # Sleep if we're going too fast (safety margin: 14 calls/sec)
        if i > 1 and i % 14 == 0:
            elapsed = time.time() - start_time
            expected_elapsed = (i / 14)  # 14 calls per second
            if elapsed < expected_elapsed:
                time.sleep(expected_elapsed - elapsed)

        # Progress logging
        if i % BATCH_SIZE == 0:
            elapsed = time.time() - start_time
            rate = i / elapsed if elapsed > 0 else 0
            log.info(f"Progress: {i}/{len(symbols)} ({rate:.1f} calls/sec, stored: {total_stored})")

        try:
            # Fetch fundamentals
            fundamentals = eodhd_client.fetch_fundamentals(symbol)
            net_income, profit_margin = eodhd_client.fundamentals_highlights(fundamentals)

            # Calculate quality score
            quality_score_val = screening.quality_score(net_income, profit_margin)

            # Additional metrics (optional)
            roe = None
            debt_to_equity = None
            current_ratio = None
            revenue_ttm = None

            # Extract additional metrics if available in fundamentals
            if fundamentals:
                highlights = fundamentals.get("Highlights", {})
                if highlights:
                    roe = highlights.get("ReturnOnEquityTTM")
                    revenue_ttm = highlights.get("RevenueTTM")

                financials = fundamentals.get("Financials", {})
                if financials:
                    balance_sheet = financials.get("Balance_Sheet", {})
                    if balance_sheet and "quarterly" in balance_sheet:
                        latest_quarter = balance_sheet["quarterly"]
                        if latest_quarter:
                            # Get the most recent quarter
                            latest_date = max(latest_quarter.keys())
                            quarter_data = latest_quarter[latest_date]

                            # debt_to_equity = total_debt / total_equity
                            total_debt = quarter_data.get("totalDebt")
                            total_equity = quarter_data.get("totalStockholderEquity")
                            if total_debt is not None and total_equity and total_equity != 0:
                                debt_to_equity = total_debt / total_equity

                            # current_ratio = current_assets / current_liabilities
                            current_assets = quarter_data.get("totalCurrentAssets")
                            current_liabilities = quarter_data.get("totalCurrentLiabilities")
                            if current_assets and current_liabilities and current_liabilities != 0:
                                current_ratio = current_assets / current_liabilities

            metrics_batch.append({
                "symbol": symbol,
                "quality_score": quality_score_val,
                "net_income": net_income,
                "profit_margin": profit_margin,
                "revenue_ttm": revenue_ttm,
                # insider_score and insider_net_value removed (US-only feature)
                "roe": roe,
                "debt_to_equity": debt_to_equity,
                "current_ratio": current_ratio,
                "data_as_of": date.today(),
            })

            fetched_count += 1

        except Exception as e:
            # Fall back to neutral scores when data unavailable
            log.debug(f"Failed to fetch {symbol}: {e}")
            metrics_batch.append({
                "symbol": symbol,
                "quality_score": 50.0,  # Neutral
                "net_income": None,
                "profit_margin": None,
                "revenue_ttm": None,
                # insider_score and insider_net_value removed (US-only feature)
                "roe": None,
                "debt_to_equity": None,
                "current_ratio": None,
                "data_as_of": date.today(),
            })
            failed_count += 1

        # Write to DB incrementally every batch_size records (fail fast!)
        if len(metrics_batch) >= batch_size:
            try:
                stored_count = storage.upsert_company_metrics(metrics_batch)
                total_stored += stored_count
                log.info(f"  ✓ Stored batch of {stored_count} metrics (total: {total_stored}/{len(symbols)})")
                metrics_batch = []  # Clear batch after successful write
            except Exception as e:
                log.error(f"Failed to store batch: {e}")
                log.error(f"  Lost {len(metrics_batch)} records - will retry on next run")
                metrics_batch = []  # Clear batch to continue
                # Don't raise - continue processing remaining symbols

    # Store any remaining metrics
    if metrics_batch:
        try:
            stored_count = storage.upsert_company_metrics(metrics_batch)
            total_stored += stored_count
            log.info(f"  ✓ Stored final batch of {stored_count} metrics (total: {total_stored})")
        except Exception as e:
            log.error(f"Failed to store final batch: {e}")
            log.error(f"  Lost {len(metrics_batch)} records")

    elapsed = time.time() - start_time

    log.info(f"✓ Completed in {elapsed:.1f}s")
    log.info(f"  Fetched: {fetched_count}, Failed: {failed_count}, Stored: {total_stored}")

    return total_stored


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run()


if __name__ == "__main__":
    main()
