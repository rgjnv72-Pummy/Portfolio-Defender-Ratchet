# Trading Engine System Architecture

## Core Directories
- **Obsidian-Journal**: `C:\Users\rgjnv\Trading-Engine\Obsidian-Journal` - Research and daily logs.
- **Ratchet-System**: `C:\Users\rgjnv\Trading-Engine\Ratchet-System` - Trade management and scanner logic.
- **Scanner-Scripts**: `C:\Users\rgjnv\Trading-Engine\Scanner-Scripts` - Utility scripts for data ingestion and synchronization.

## Active Scripts
- `weekend_sync.py`: Synchronizes data during weekends.
- `telegram_parser.py`: Parses trading signals from Telegram.
- `pdf_importer.py`: Imports data from PDF ledgers.
- `exit_auditor.py`: Audits trade exits and performance.
- `manual_ingestor.py`: Manually ingests trade data.
- `position_sizer.py`: Calculates position sizes based on risk parameters. (Note: Script file not yet present in workspace).

## Database Files
- `Ratchet-System/portfolio.json`: Current holdings and equity value.
- `Ratchet-System/closed_trades.json`: History of completed trades.

## Quantitative Risk Boundaries
- **Portfolio Risk**: 1% risk per trade.
- **Max Loss**: ₹19,438 maximum loss allowed.
- **APTUS.NS Stop Floor**: ₹252.9 (strictly enforced).
