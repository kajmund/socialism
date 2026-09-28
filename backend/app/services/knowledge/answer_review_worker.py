"""Separate, bounded review queue process. Never invoked by research.

python -m app.services.knowledge.answer_review_worker enqueue --limit 100
python -m app.services.knowledge.answer_review_worker list --customer-id 7
python -m app.services.knowledge.answer_review_worker complete --customer-id 7 --id HASH
"""

import argparse
import asyncio
import json

from app.database.session import SessionLocal, engine
from app.services.knowledge.answer_review import (
    complete_review,
    enqueue_due_reviews,
    list_review_candidates,
)


async def run(args: argparse.Namespace) -> object:
    async with SessionLocal() as session:
        if args.action == "enqueue":
            result = await enqueue_due_reviews(session, limit=args.limit)
            await session.commit()
            return {"candidate_ids": result}
        if args.action == "complete":
            completed = await complete_review(
                session,
                customer_id=args.customer_id,
                answer_id=args.id,
            )
            await session.commit()
            return {"completed": completed}
        rows = await list_review_candidates(
            session,
            customer_id=args.customer_id,
            limit=args.limit,
        )
        return [
            {
                "id": row.id,
                "customer_id": row.customer_id,
                "question": row.question,
                "question_key": row.question_key,
                "claim_ids": row.claim_ids,
                "ttl": row.ttl,
                "created_at": row.created_at,
                "review_after": row.review_after,
                "candidate_at": row.candidate_at,
            }
            for row in rows
        ]


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    enqueue = commands.add_parser("enqueue")
    enqueue.add_argument("--limit", type=int, default=100)
    listing = commands.add_parser("list")
    listing.add_argument("--customer-id", type=int, required=True)
    listing.add_argument("--limit", type=int, default=100)
    complete = commands.add_parser("complete")
    complete.add_argument("--customer-id", type=int, required=True)
    complete.add_argument("--id", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(await run(args), ensure_ascii=False, default=str))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
