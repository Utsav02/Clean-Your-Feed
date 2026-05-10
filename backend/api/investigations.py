"""
Investigation API routes.

POST /investigations         — start a new investigation
GET  /investigations         — list all past investigations
GET  /investigations/{id}    — full report
GET  /investigations/{id}/stream — SSE stage events
"""

import asyncio
import json
from enum import Enum
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend import config
from backend.db import queries
from backend.core import investigator, analyzer

router = APIRouter(prefix="/investigations", tags=["investigations"])

# In-memory SSE queues keyed by investigation_id.
# Created before the background task starts, so events are buffered even if
# the client connects slightly after the task begins.
_sse_queues: dict[int, asyncio.Queue] = {}

TERMINAL_STAGES = {"COMPLETE", "FAILED"}


class DepthEnum(str, Enum):
    QUICK = "QUICK"
    STANDARD = "STANDARD"
    DEEP = "DEEP"


class StartInvestigationBody(BaseModel):
    seed_text: str
    depth: DepthEnum = DepthEnum.STANDARD
    narrative_label: str | None = None


class ProfileInvestigationBody(BaseModel):
    handles_text: str
    depth: DepthEnum = DepthEnum.STANDARD
    min_cluster_size: int = 2
    narrative_label: str | None = None


class ReplyInvestigationBody(BaseModel):
    tweet_url: str
    depth: DepthEnum = DepthEnum.STANDARD
    narrative_label: str | None = None


async def _maybe_label(investigation_id: int, narrative_label: str | None) -> None:
    if narrative_label and narrative_label.strip():
        await queries.label_investigation(config.DATABASE_PATH, investigation_id, narrative_label.strip())


async def _run_and_cleanup(
    investigation_id: int,
    db_path: str,
    seed_text: str,
    depth: str,
    emit: investigator.EmitFn,
) -> None:
    """Wrapper that guarantees the SSE queue is removed when the pipeline ends."""
    try:
        await investigator.run_investigation(db_path, investigation_id, seed_text, depth, emit)
    finally:
        _sse_queues.pop(investigation_id, None)


async def _run_reply_and_cleanup(
    investigation_id: int,
    db_path: str,
    tweet_url: str,
    depth: str,
    emit: investigator.EmitFn,
) -> None:
    try:
        await investigator.run_reply_investigation(
            db_path, investigation_id, tweet_url, depth, emit
        )
    finally:
        _sse_queues.pop(investigation_id, None)


async def _run_profile_and_cleanup(
    investigation_id: int,
    db_path: str,
    handles_text: str,
    depth: str,
    min_cluster_size: int,
    emit: investigator.EmitFn,
) -> None:
    try:
        await investigator.run_profile_investigation(
            db_path, investigation_id, handles_text, depth, emit, min_cluster_size
        )
    finally:
        _sse_queues.pop(investigation_id, None)


def _status_code(cached: dict | None) -> int:
    return 200 if cached else 201


@router.post("", status_code=201)
async def create_investigation(body: StartInvestigationBody):
    cached = await queries.find_cached_investigation(
        config.DATABASE_PATH, body.seed_text, "TWEET", body.depth.value
    )
    if cached:
        await _maybe_label(cached["id"], body.narrative_label)
        return {"investigation_id": cached["id"], "cached": True}

    investigation_id = await queries.create_investigation(
        config.DATABASE_PATH, body.seed_text, body.depth.value,
        investigation_type="TWEET",
    )
    await _maybe_label(investigation_id, body.narrative_label)

    q: asyncio.Queue = asyncio.Queue()
    _sse_queues[investigation_id] = q

    async def emit(stage: str, message: str) -> None:
        await q.put({"stage": stage, "message": message})

    asyncio.create_task(
        _run_and_cleanup(
            investigation_id,
            config.DATABASE_PATH,
            body.seed_text,
            body.depth.value,
            emit,
        )
    )

    return {"investigation_id": investigation_id, "cached": False}


@router.post("/replies", status_code=201)
async def create_reply_investigation(body: ReplyInvestigationBody):
    cached = await queries.find_cached_investigation(
        config.DATABASE_PATH, body.tweet_url, "REPLIES", body.depth.value
    )
    if cached:
        await _maybe_label(cached["id"], body.narrative_label)
        return {"investigation_id": cached["id"], "cached": True}

    investigation_id = await queries.create_investigation(
        config.DATABASE_PATH, body.tweet_url, body.depth.value,
        investigation_type="REPLIES",
    )
    await _maybe_label(investigation_id, body.narrative_label)

    q: asyncio.Queue = asyncio.Queue()
    _sse_queues[investigation_id] = q

    async def emit(stage: str, message: str) -> None:
        await q.put({"stage": stage, "message": message})

    asyncio.create_task(
        _run_reply_and_cleanup(
            investigation_id,
            config.DATABASE_PATH,
            body.tweet_url,
            body.depth.value,
            emit,
        )
    )

    return {"investigation_id": investigation_id, "cached": False}


@router.post("/profile", status_code=201)
async def create_profile_investigation(body: ProfileInvestigationBody):
    cached = await queries.find_cached_investigation(
        config.DATABASE_PATH, body.handles_text, "PROFILES", body.depth.value
    )
    if cached:
        await _maybe_label(cached["id"], body.narrative_label)
        return {"investigation_id": cached["id"], "cached": True}

    investigation_id = await queries.create_investigation(
        config.DATABASE_PATH, body.handles_text, body.depth.value,
        investigation_type="PROFILES",
    )
    await _maybe_label(investigation_id, body.narrative_label)

    q: asyncio.Queue = asyncio.Queue()
    _sse_queues[investigation_id] = q

    async def emit(stage: str, message: str) -> None:
        await q.put({"stage": stage, "message": message})

    asyncio.create_task(
        _run_profile_and_cleanup(
            investigation_id,
            config.DATABASE_PATH,
            body.handles_text,
            body.depth.value,
            body.min_cluster_size,
            emit,
        )
    )

    return {"investigation_id": investigation_id, "cached": False}


@router.get("/{investigation_id}/stream")
async def stream_investigation(investigation_id: int):
    inv = await queries.get_investigation(config.DATABASE_PATH, investigation_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="Investigation not found")

    # If already terminal, stream nothing (client should GET the report directly)
    if inv["status"] in TERMINAL_STAGES and investigation_id not in _sse_queues:
        async def terminal_stream() -> AsyncGenerator[str, None]:
            payload = (
                {"stage": inv["status"], "investigation_id": investigation_id}
                if inv["status"] == "COMPLETE"
                else {"stage": "FAILED", "reason": inv.get("failure_reason", "")}
            )
            yield f"data: {json.dumps(payload)}\n\n"

        return StreamingResponse(terminal_stream(), media_type="text/event-stream")

    q = _sse_queues.setdefault(investigation_id, asyncio.Queue())

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=60.0)
                except asyncio.TimeoutError:
                    # Send a keep-alive comment so the connection doesn't drop
                    yield ": keep-alive\n\n"
                    continue

                stage = event.get("stage")

                if stage == "COMPLETE":
                    payload = {"stage": "COMPLETE", "investigation_id": investigation_id}
                elif stage == "FAILED":
                    payload = {"stage": "FAILED", "reason": event.get("message", "")}
                else:
                    payload = {"stage": stage, "message": event.get("message", "")}

                yield f"data: {json.dumps(payload)}\n\n"

                if stage in TERMINAL_STAGES:
                    break
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/top")
async def top_investigations(
    verdict: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    rows = await queries.list_top_investigations(
        config.DATABASE_PATH, verdict=verdict, limit=limit, offset=offset
    )
    return rows


@router.get("/narratives")
async def list_narratives():
    return await queries.list_narratives(config.DATABASE_PATH)


@router.get("/{investigation_id}")
async def get_investigation(investigation_id: int):
    report = await queries.get_investigation_report(config.DATABASE_PATH, investigation_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return report


class LabelBody(BaseModel):
    label: str


@router.post("/{investigation_id}/label", status_code=201)
async def label_investigation(investigation_id: int, body: LabelBody):
    inv = await queries.get_investigation(config.DATABASE_PATH, investigation_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    narrative = await queries.label_investigation(config.DATABASE_PATH, investigation_id, body.label.strip())
    return narrative


@router.get("/{investigation_id}/labels")
async def get_investigation_labels(investigation_id: int):
    return await queries.get_investigation_labels(config.DATABASE_PATH, investigation_id)


@router.get("/{investigation_id}/evidence")
async def get_evidence(investigation_id: int):
    inv = await queries.get_investigation(config.DATABASE_PATH, investigation_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return await queries.get_investigation_evidence(config.DATABASE_PATH, investigation_id)


@router.get("/{investigation_id}/profile-analysis")
async def get_profile_analysis(investigation_id: int):
    """
    Analyse stored timelines of cell members. No API calls — pure DB read.
    Returns per-account reply targets, shared targets across the cell,
    and thematic clusters from their historical replies.
    """
    inv = await queries.get_investigation(config.DATABASE_PATH, investigation_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="Investigation not found")

    tweets = await queries.get_cell_member_tweets(config.DATABASE_PATH, investigation_id)

    report = await queries.get_investigation_report(config.DATABASE_PATH, investigation_id)
    cell_members  = report["cell_members"]  if report else []
    tweet_matches = report["tweet_matches"] if report else []
    investigation = report["investigation"] if report else {}

    if not tweets and not cell_members:
        return {
            "accounts": [], "shared_targets": [], "theme_clusters": [],
            "self_repetitions": {}, "timing": {}, "coordination_score": None,
        }

    profile_result = analyzer.analyze_profiles(tweets) if tweets else {
        "accounts": [], "shared_targets": [], "theme_clusters": [], "self_repetitions": {}
    }

    # Attach reply_ratio from profile analysis back to cell_members for scoring
    ratio_map = {a["account_id"]: a["reply_ratio"] for a in profile_result["accounts"]}
    for m in cell_members:
        m["reply_ratio"] = ratio_map.get(m["account_id"], 0.0)

    # Resolve seed tweet posted_at for reply-speed analysis
    seed_posted_at: int | None = None
    seed_tweet_id = investigation.get("seed_tweet_id")
    if seed_tweet_id:
        seed_row = await queries.get_tweet(config.DATABASE_PATH, seed_tweet_id)
        if seed_row:
            seed_posted_at = seed_row.get("posted_at")

    timing = analyzer.analyze_timing(
        cell_members,
        tweet_matches,
        seed_posted_at,
    )

    coordination = analyzer.cell_coordination_score(
        cell_members,
        timing,
        profile_result["shared_targets"],
        profile_result["theme_clusters"],
    )

    return {
        **profile_result,
        "timing":               timing,
        "coordination_score":   coordination,
        "investigation_type":   investigation.get("investigation_type", "TWEET"),
    }


@router.get("")
async def list_investigations():
    rows = await queries.list_investigations(config.DATABASE_PATH)
    return rows
