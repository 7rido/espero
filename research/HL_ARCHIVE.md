# Hyperliquid's archive — what is documented, and what has not been checked

**Status, 2026-10-31: the buckets have not been listed, and the user has declined AWS** (so this study stopped:
[RESULTS_HLABSORB.md](RESULTS_HLABSORB.md)). Both refuse anonymous requests ("Anonymous users cannot
invoke requests against Requester Pays buckets"). Listing needs an AWS account paying for the request. This machine
has no AWS CLI and no credentials file, and an agent here does not create accounts or handle keys. Everything below
is what documentation says, not what is in the buckets.

**Correction.** `espero/hlbook.py` said Hyperliquid has no history of its book. That was wrong, and the author
repeated it to the user. Hyperliquid documents L2 snapshots in S3. The API does serve only the current book.

## Checked directly

| bucket | anonymous request | region |
|---|---|---|
| `hyperliquid-archive` | HTTP 403, requester pays | us-east-1 |
| `hl-mainnet-node-data` | HTTP 403, requester pays | ap-northeast-1 |

## Documented by Hyperliquid

| path | contents | caveat |
|---|---|---|
| `hyperliquid-archive/market_data/[date]/[hour]/[datatype]/[coin].lz4` | L2 book snapshots | uploaded about monthly; "no guarantee of timely updates and data may be missing" |
| `hyperliquid-archive/asset_ctxs/[date].csv.lz4` | asset contexts | same |
| `hl-mainnet-node-data/node_fills_by_block` | fills, current format | dates not stated |
| `hl-mainnet-node-data/node_fills` | fills, older, API format | dates not stated |
| `hl-mainnet-node-data/node_trades` | trades, older, not API format | dates not stated |
| `hl-mainnet-node-data/explorer_blocks` | explorer blocks | dates not stated |
| `hl-mainnet-node-data/replica_cmds` | L1 transactions | dates not stated |
| `hl-mainnet-node-data/misc_events_by_block` | transfers, staking, funding events | dates not stated |

Hyperliquid's page does not mention order-level data, and does not say which sets carry addresses.

## Described only by a vendor

Dwellir describes `node_order_statuses_by_block/<YYYYMMDD>/<hour>.lz4` and order-level raw book diffs, with a `user`
field. It gives no bucket name, and its pages disagree on dates: "2026-01-22 to today" and "2026-01-22 to 2026-09-28".
Its field list comes from one file. **Whether these are in Hyperliquid's buckets is unknown.** If 2026-01-22 is right,
order-level history covers about nine months before this study's 2026-10-30 cut-off, and excludes the October 2025
cascade.

## What the archive does and does not replace in `data/hlbook/`

| | our recorder | S3 snapshots | order-level diffs, if they exist |
|---|---|---|---|
| history before 2026-10-31 | none | **yes, dates unlisted** | from about 2026-01, unverified |
| available the same day | **yes** | no, about monthly | unknown |
| cost | free | requester pays | requester pays |
| depth and frequency | top 20 levels, 5 minutes, 10 coins | unknown until a file is read | every change, if complete |
| who owns each order | no | no | `user` field, if complete |

**Decision: the recorder keeps running unchanged.** It is the only same-day copy, and it is an independent check on
the archive's snapshots. It adds nothing to this study, whose data stops before 2026-10-30, and it may be redundant for
research if the order-level feed proves complete. That can only be judged after a listing.

## The listing, for the account holder to run

It needs an AWS account and the AWS CLI, set up by the holder in their own terminal. `LIST` requests are billed to the
caller at a fraction of a cent per thousand, and each returns up to 1,000 file names, so this is expected to cost under a
dollar. That is an estimate, since the file count is unknown. No file is downloaded, and the output holds no key. It goes
in `data/pit/`, which is git-ignored:

    aws s3 ls --recursive --summarize --request-payer requester s3://hyperliquid-archive/ > data/pit/hl_s3_archive.txt
    aws s3 ls --recursive --summarize --request-payer requester s3://hl-mainnet-node-data/ > data/pit/hl_s3_node.txt

## Not verified

- Every date, size and field above, until the listing and a sample file are read.
- Transfer cost: it needs the sizes, and they are unknown.
