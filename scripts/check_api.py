"""Read-only IBKR API connectivity check.

Confirms TWS's API is reachable and the account is readable BEFORE we build the
order-placing side (task #5). Connects read-only (both via the connect() flag and
because we only ever call query methods), prints a curated account summary +
open positions, and disconnects. Places//modifies NOTHING — safe to run with
"Read-Only API" left checked in TWS.

Bonus: it prints DayTradesRemaining (T..T+4), which answers the PDT question
directly from the source instead of hunting through the UI.

Usage:
    python scripts/check_api.py                 # live TWS (port 7496)
    python scripts/check_api.py --paper         # paper TWS (port 7497)
    python scripts/check_api.py --port 7496 --client-id 9
"""

import argparse
import sys

# Tags worth seeing for this account/strategy (buying power, PDT, cash split).
WANT = [
    "AccountType", "NetLiquidation", "TotalCashValue", "SettledCash",
    "BuyingPower", "AvailableFunds", "Cushion",
    "DayTradesRemaining", "DayTradesRemainingT+1", "DayTradesRemainingT+2",
    "DayTradesRemainingT+3", "DayTradesRemainingT+4",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=None,
                    help="TWS socket port (default 7496 live, 7497 with --paper)")
    ap.add_argument("--paper", action="store_true", help="use the paper port 7497")
    ap.add_argument("--client-id", type=int, default=9)
    args = ap.parse_args()
    port = args.port if args.port is not None else (7497 if args.paper else 7496)

    try:
        from ib_async import IB
    except ImportError:
        print("ib_async not installed. Run: ./.venv/bin/python -m pip install ib_async")
        return 1

    ib = IB()
    try:
        # readonly=True makes the client refuse to transmit any order — belt and
        # suspenders alongside TWS's own Read-Only API setting.
        ib.connect(args.host, port, clientId=args.client_id, readonly=True, timeout=15)
    except Exception as e:
        print(f"COULD NOT CONNECT to {args.host}:{port} (clientId {args.client_id})")
        print(f"  {type(e).__name__}: {e}")
        print("  Checklist: TWS running & logged in · 'Enable ActiveX and Socket "
              "Clients' checked · port matches (7496 live / 7497 paper) · "
              "clientId not already in use.")
        return 1

    print(f"CONNECTED to {args.host}:{port}  ·  server v{ib.client.serverVersion()}")
    accounts = ib.managedAccounts()
    print(f"accounts: {', '.join(accounts) or '—'}\n")

    summary = {av.tag: av.value for av in ib.accountSummary()}
    print("ACCOUNT SUMMARY")
    for tag in WANT:
        if tag in summary:
            print(f"  {tag:<24} {summary[tag]}")

    positions = ib.positions()
    print(f"\nOPEN POSITIONS ({len(positions)})")
    for p in positions:
        print(f"  {p.contract.symbol:<6} {p.position:>10.4f} @ avg "
              f"{p.avgCost:>10.4f}  [{p.contract.secType}]")

    ib.disconnect()
    print("\nOK — API reachable, read-only. (No orders were sent.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
