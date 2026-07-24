import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.config import settings
from app.core.response import ApiResponse
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.onboarding import OnboardingSession, ProfileMessage
from app.models.ai_config import AIModelConfig, PromptVersion
from app.models.profile import DirectionRecommendation, InvestmentProfile
from app.models.user import User
from app.schemas.onboarding import AITurnResult, EvidenceConfirmationResponse, MessageInput, MessageTurnResponse, ObjectiveProfileInput, ProfileDimension, ProfileWithRecommendationsResponse, SessionResponse, SkipInput
from app.services.ai_orchestrator import AIAdapterRegistry, INITIAL_RISK_QUESTION, ONBOARDING_SYSTEM_PROMPT, PROFILE_DIMENSIONS, SENSITIVE_DIMENSIONS, get_ai_adapter_registry, server_question
from app.services.profile_rules import assess_profile, rank_directions

router = APIRouter()
MESSAGE_CLAIM_LEASE = timedelta(minutes=2)


def unresolved_dimensions(session: OnboardingSession) -> list[str]:
    return [
        dimension
        for dimension in PROFILE_DIMENSIONS
        if dimension not in session.skipped_dimensions
        and float(session.dimension_scores.get(dimension, 0.0)) < 0.6
        and int(session.followup_counts.get(dimension, 0)) < 2
    ]


def remaining_dimensions(session: OnboardingSession) -> list[str]:
    unresolved = unresolved_dimensions(session)
    if unresolved:
        return unresolved
    if session.round_count < session.min_rounds:
        return [
            dimension
            for dimension in PROFILE_DIMENSIONS
            if dimension not in session.skipped_dimensions
            and int(session.followup_counts.get(dimension, 0)) < 2
        ]
    return []


def refresh_progress(session: OnboardingSession) -> list[str]:
    remaining = remaining_dimensions(session)
    resolved = len(PROFILE_DIMENSIONS) - len(unresolved_dimensions(session))
    session.completeness = round(0.4 + 0.6 * resolved / len(PROFILE_DIMENSIONS), 2)
    session.current_dimension = remaining[0] if remaining else None
    return remaining


def projected_progress_after_acceptance(
    session: OnboardingSession,
    *,
    dimension: str,
    confidence: float,
    proposed_followup_count: int,
    proposed_round_count: int,
) -> tuple[list[str], float, str | None]:
    scores = dict(session.dimension_scores)
    scores[dimension] = max(float(scores.get(dimension, 0.0)), confidence)
    counts = dict(session.followup_counts)
    counts[dimension] = proposed_followup_count
    unresolved = [
        item
        for item in PROFILE_DIMENSIONS
        if item not in session.skipped_dimensions
        and float(scores.get(item, 0.0)) < 0.6
        and int(counts.get(item, 0)) < 2
    ]
    resolved = len(PROFILE_DIMENSIONS) - len(unresolved)
    completeness = round(0.4 + 0.6 * resolved / len(PROFILE_DIMENSIONS), 2)
    remaining = unresolved
    if not remaining and proposed_round_count < session.min_rounds:
        remaining = [
            item
            for item in PROFILE_DIMENSIONS
            if item not in session.skipped_dimensions
            and int(counts.get(item, 0)) < 2
        ]
    return remaining, completeness, remaining[0] if remaining else None


def serialize_session(session: OnboardingSession) -> dict:
    return SessionResponse.model_validate(session).model_dump(mode="json")


async def owned_session(db: AsyncSession, session_id: str, user_id: str) -> OnboardingSession:
    session = await db.scalar(
        select(OnboardingSession).where(
            OnboardingSession.id == session_id,
            OnboardingSession.user_id == user_id,
        )
    )
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Onboarding session not found")
    return session


async def message_request(
    db: AsyncSession, session_id: str, request_id: str
) -> ProfileMessage | None:
    return await db.scalar(
        select(ProfileMessage).where(
            ProfileMessage.session_id == session_id,
            ProfileMessage.request_id == request_id,
            ProfileMessage.role == "user",
        )
    )


async def replay_message_response(db: AsyncSession, user_message: ProfileMessage) -> dict:
    response = user_message.extracted_data.get("response")
    if isinstance(response, dict):
        return response
    assistant_message = await db.scalar(
        select(ProfileMessage).where(
            ProfileMessage.parent_message_id == user_message.id,
            ProfileMessage.role == "assistant",
        )
    )
    if assistant_message is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Message request is still being processed",
        )
    response = assistant_message.extracted_data.get("response")
    if not isinstance(response, dict):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Message request result is unavailable",
        )
    return response


async def inflight_message(db: AsyncSession, session_id: str) -> ProfileMessage | None:
    completed_parent_ids = select(ProfileMessage.parent_message_id).where(
        ProfileMessage.parent_message_id.is_not(None)
    )
    candidates = (
        await db.scalars(
            select(ProfileMessage)
            .where(
                ProfileMessage.session_id == session_id,
                ProfileMessage.role == "user",
                ProfileMessage.request_id.is_not(None),
                ProfileMessage.id.not_in(completed_parent_ids),
            )
            .order_by(ProfileMessage.created_at)
        )
    ).all()
    claim = next(
        (
            item
            for item in candidates
            if not isinstance(item.extracted_data.get("response"), dict)
        ),
        None,
    )
    if claim is None:
        return None
    created_at = claim.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if created_at >= datetime.now(timezone.utc) - MESSAGE_CLAIM_LEASE:
        return claim
    await release_message_claim(db, session_id, claim.id)
    return None


async def release_message_claim(
    db: AsyncSession, session_id: str, message_id: str
) -> None:
    for attempt in range(2):
        try:
            claim = await db.get(ProfileMessage, message_id)
            if claim is None:
                return
            session = await db.get(OnboardingSession, session_id)
            await db.delete(claim)
            if session is not None and session.turn_count > 0:
                session.turn_count -= 1
            await db.commit()
            return
        except StaleDataError:
            await db.rollback()
            if attempt:
                raise


async def completed_profile_response(
    db: AsyncSession, profile: InvestmentProfile
) -> dict:
    recommendations = (
        await db.scalars(
            select(DirectionRecommendation)
            .where(DirectionRecommendation.profile_id == profile.id)
            .order_by(DirectionRecommendation.rank)
        )
    ).all()
    return {
        "profile": serialize_profile(profile),
        "recommendations": [serialize_recommendation(item) for item in recommendations],
    }


@router.post("/sessions", status_code=status.HTTP_201_CREATED, response_model=ApiResponse[SessionResponse])
async def create_session(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    adapter_registry: AIAdapterRegistry = Depends(get_ai_adapter_registry),
) -> ApiResponse:
    user_id = user.id
    existing = await db.scalar(
        select(OnboardingSession)
        .where(OnboardingSession.user_id == user_id, OnboardingSession.status.in_(("active", "ready")))
        .order_by(OnboardingSession.created_at.desc())
    )
    if existing is not None:
        return ApiResponse.ok(serialize_session(existing))
    config = await db.scalar(
        select(AIModelConfig).where(
            AIModelConfig.capability == "text", AIModelConfig.enabled.is_(True)
        )
    )
    if settings.app_env != "development" and (
        config is None or config.provider == "mock"
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Production onboarding requires an enabled non-mock text provider",
        )
    if config is not None and config.provider not in adapter_registry.text_providers:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configured text provider is not available",
        )
    session = OnboardingSession(
        user_id=user_id,
        live_key=user_id,
        provider_name=config.provider if config else "mock",
        model_name=config.model_name if config else "mock",
        prompt_version=config.prompt_version if config else "v1",
        min_rounds=config.min_rounds if config else 6,
        max_rounds=config.max_rounds if config else 12,
        prompt_id=None,
        prompt_hash="",
        prompt_content="",
    )
    prompt = await db.scalar(
        select(PromptVersion).where(PromptVersion.version == session.prompt_version)
    )
    if prompt is None and config is not None and session.prompt_version != "v1":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Configured Prompt version does not exist",
        )
    session.prompt_id = prompt.id if prompt else None
    session.prompt_content = prompt.content if prompt else ONBOARDING_SYSTEM_PROMPT
    session.prompt_hash = hashlib.sha256(session.prompt_content.encode("utf-8")).hexdigest()
    db.add(session)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        existing = await db.scalar(
            select(OnboardingSession).where(OnboardingSession.live_key == user_id)
        )
        if existing is None:
            raise
        return ApiResponse.ok(serialize_session(existing))
    return ApiResponse.ok(serialize_session(session))


@router.get("/sessions/current", response_model=ApiResponse[SessionResponse])
async def current_session(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse:
    session = await db.scalar(
        select(OnboardingSession)
        .where(OnboardingSession.user_id == user.id, OnboardingSession.status.in_(("active", "ready")))
        .order_by(OnboardingSession.created_at.desc())
    )
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active onboarding session")
    return ApiResponse.ok(serialize_session(session))


@router.put("/sessions/{session_id}/objective-profile", response_model=ApiResponse[SessionResponse])
async def update_objective_profile(
    session_id: str,
    body: ObjectiveProfileInput,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    session = await owned_session(db, session_id, user.id)
    if session.status != "active" or session.step != "objective_profile":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is not active")
    session.objective_profile = body.model_dump(mode="json")
    session.step = "conversation"
    session.current_dimension = PROFILE_DIMENSIONS[0]
    session.current_question = INITIAL_RISK_QUESTION
    session.completeness = 0.4
    await db.flush()
    return ApiResponse.ok(serialize_session(session))


@router.post(
    "/sessions/{session_id}/messages",
    response_model=ApiResponse[MessageTurnResponse | EvidenceConfirmationResponse],
)
async def add_message(
    session_id: str,
    body: MessageInput,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    adapter_registry: AIAdapterRegistry = Depends(get_ai_adapter_registry),
) -> ApiResponse:
    session = await owned_session(db, session_id, user.id)
    request_id = str(body.request_id) if body.request_id is not None else None
    if request_id is not None:
        previous_request = await message_request(db, session.id, request_id)
        if previous_request is not None:
            return ApiResponse.ok(await replay_message_response(db, previous_request))

    pending = dict(session.pending_profile_evidence)
    if pending and body.confirm_pending is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pending profile evidence must be confirmed or rejected before continuing",
        )
    if not pending and body.confirm_pending is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No pending profile evidence")
    if pending and body.confirm_pending is not None:
        accepted = body.confirm_pending
        pending_dimension = pending["dimension"]
        pending_value = pending.get("value")
        confirmed = dict(session.profile_evidence)
        if accepted and pending_value is not None:
            confirmed[pending_dimension] = pending_value
        session.profile_evidence = confirmed
        session.pending_profile_evidence = {}
        if accepted:
            counts = dict(session.followup_counts)
            counts[pending_dimension] = pending["proposed_followup_count"]
            scores = dict(session.dimension_scores)
            scores[pending_dimension] = max(
                float(scores.get(pending_dimension, 0.0)),
                float(pending["confidence"]),
            )
            session.followup_counts = counts
            session.dimension_scores = scores
            session.round_count = pending["proposed_round_count"]
        confirmed_evidence = (
            {pending_dimension: pending_value}
            if accepted and pending_value is not None
            else {}
        )
        confirmation_message = ProfileMessage(
            session_id=session.id,
            request_id=request_id,
            role="user",
            content="Confirmed extracted evidence" if accepted else "Rejected extracted evidence",
            input_mode="text",
            target_dimension=pending_dimension,
            sensitive=pending_dimension in SENSITIVE_DIMENSIONS,
            refused=not accepted,
            extracted_data=confirmed_evidence,
        )
        db.add(confirmation_message)
        remaining_after_confirmation = refresh_progress(session)
        reached_call_limit = session.turn_count >= session.max_rounds
        accepted_terminal = accepted and (
            not remaining_after_confirmation
            or session.completeness >= 0.8
            or not pending["should_continue"]
        )
        if not remaining_after_confirmation or (
            session.turn_count >= session.min_rounds
            and (reached_call_limit or accepted_terminal)
        ):
            session.status = "ready"
            session.step = "ready"
            session.current_dimension = None
            session.current_question = None
        elif accepted:
            session.current_question = pending["next_question"]
        else:
            session.current_question = pending["retry_question"]
        try:
            await db.flush()
            response = {
                "session": serialize_session(session),
                "accepted": accepted,
                "confirmed_evidence": confirmed_evidence,
            }
            confirmation_message.extracted_data = {
                "confirmed_evidence": confirmed_evidence,
                "response": response,
            }
            await db.flush()
        except (IntegrityError, StaleDataError) as exc:
            await db.rollback()
            previous_request = await message_request(db, session_id, request_id)
            if previous_request is not None:
                return ApiResponse.ok(
                    await replay_message_response(db, previous_request)
                )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Confirmation conflicts with another session update",
            ) from exc
        return ApiResponse.ok(response)
    if session.status != "active" or session.step != "conversation":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is not accepting messages")
    if session.turn_count >= session.max_rounds:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conversation round limit reached")

    if await inflight_message(db, session.id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another message request is still being processed",
        )

    try:
        orchestrator = adapter_registry.resolve_text(
            provider=session.provider_name,
            model_name=session.model_name,
            system_prompt=session.prompt_content,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configured AI provider is unavailable",
        ) from exc

    target_snapshot = session.current_dimension
    round_count_snapshot = session.round_count
    max_rounds_snapshot = session.max_rounds
    completeness_snapshot = session.completeness
    dimension_scores_snapshot = dict(session.dimension_scores)
    followup_counts_snapshot = dict(session.followup_counts)
    skipped_dimensions_snapshot = list(session.skipped_dimensions)
    request_id = request_id or str(uuid.uuid4())
    user_message = ProfileMessage(
        session_id=session.id,
        request_id=request_id,
        role="user",
        content=body.content,
        input_mode=body.input_mode.value,
        target_dimension=target_snapshot,
        sensitive=target_snapshot in SENSITIVE_DIMENSIONS,
    )
    session.turn_count += 1
    db.add(user_message)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        previous_request = await message_request(db, session_id, request_id)
        if previous_request is not None:
            return ApiResponse.ok(await replay_message_response(db, previous_request))
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Message request conflicts with another request",
        )
    except StaleDataError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Onboarding session changed; retry the message",
        ) from exc

    next_completeness = min(1.0, max(completeness_snapshot, 0.5) + 0.05)
    try:
        raw_turn = await orchestrator.respond(
            content=body.content,
            round_count=round_count_snapshot,
            turn_count=session.turn_count,
            min_rounds=session.min_rounds,
            max_rounds=max_rounds_snapshot,
            completeness=next_completeness,
            dimension_scores=dimension_scores_snapshot,
            followup_counts=followup_counts_snapshot,
            skipped_dimensions=skipped_dimensions_snapshot,
            current_dimension=target_snapshot,
        )
    except TimeoutError as exc:
        await release_message_claim(db, session_id, user_message.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI provider timed out; retry without losing progress",
        ) from exc
    except Exception as exc:
        await release_message_claim(db, session_id, user_message.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI provider failed before returning a structured response",
        ) from exc
    try:
        turn = AITurnResult.model_validate(raw_turn)
    except ValidationError as exc:
        await release_message_claim(db, session_id, user_message.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI provider returned an invalid structured response",
        ) from exc
    target = turn.target_dimension.value
    expected_sensitive = target in SENSITIVE_DIMENSIONS
    if (
        target != target_snapshot
        or target in skipped_dimensions_snapshot
        or int(followup_counts_snapshot.get(target, 0)) >= 2
        or turn.sensitive != expected_sensitive
    ):
        await release_message_claim(db, session_id, user_message.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI provider returned a disallowed profile dimension",
        )
    proposed_followup_count = int(followup_counts_snapshot.get(target, 0)) + 1
    projected_remaining, projected_completeness, projected_dimension = (
        projected_progress_after_acceptance(
            session,
            dimension=target,
            confidence=turn.confidence,
            proposed_followup_count=proposed_followup_count,
            proposed_round_count=round_count_snapshot + 1,
        )
    )
    reached_call_limit = session.turn_count >= session.max_rounds
    projected_ready = not projected_remaining or (
        session.turn_count >= session.min_rounds
        and (
            reached_call_limit
            or projected_completeness >= 0.8
            or not turn.should_continue
        )
    )
    returned_next_dimension = (
        turn.next_question_dimension.value
        if turn.next_question_dimension is not None
        else None
    )
    if (
        projected_ready
        and (turn.next_question is not None or returned_next_dimension is not None)
    ) or (
        not projected_ready
        and (
            turn.next_question is None
            or returned_next_dimension != projected_dimension
        )
    ):
        await release_message_claim(db, session_id, user_message.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI provider returned an invalid next profile question",
        )
    user_message.target_dimension = target
    user_message.sensitive = turn.sensitive
    user_message.extracted_data = turn.model_dump(mode="json")["profile_delta"]
    assistant_message = ProfileMessage(
        session_id=session.id,
        parent_message_id=user_message.id,
        role="assistant",
        content=turn.reply,
        input_mode="text",
        target_dimension=target,
        sensitive=turn.sensitive,
    )
    session.pending_profile_evidence = {
        "dimension": target,
        "value": turn.profile_delta.get(turn.target_dimension),
        "confidence": turn.confidence,
        "proposed_followup_count": proposed_followup_count,
        "proposed_round_count": round_count_snapshot + 1,
        "should_continue": turn.should_continue and not reached_call_limit,
        "end_reason": "max_turns" if reached_call_limit else turn.end_reason,
        "next_question": turn.next_question,
        "next_question_dimension": returned_next_dimension,
        "retry_question": turn.retry_question,
    }
    db.add(assistant_message)
    try:
        await db.flush()
        response = {
            "session": serialize_session(session),
            "user_message": {"id": user_message.id, "content": user_message.content, "input_mode": user_message.input_mode},
            "assistant_message": {"id": assistant_message.id, "content": assistant_message.content},
            "turn": turn.model_dump(mode="json"),
        }
        assistant_message.extracted_data = {"turn": turn.model_dump(mode="json"), "response": response}
        await db.flush()
    except StaleDataError as exc:
        await db.rollback()
        await release_message_claim(db, session_id, user_message.id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Onboarding session changed while the message was processed",
        ) from exc
    return ApiResponse.ok(response)


@router.post("/sessions/{session_id}/skip", response_model=ApiResponse[SessionResponse])
async def skip_dimension(
    session_id: str,
    body: SkipInput,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    session = await owned_session(db, session_id, user.id)
    dimension = body.dimension.value
    if session.pending_profile_evidence:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pending profile evidence must be confirmed or rejected before skipping",
        )
    if session.status != "active" or session.step != "conversation":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is not accepting skips")
    if dimension not in SENSITIVE_DIMENSIONS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Only sensitive dimensions may be skipped")
    if dimension != session.current_dimension:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only the current dimension may be skipped")
    skipped = list(session.skipped_dimensions)
    if dimension not in skipped:
        skipped.append(dimension)
    session.skipped_dimensions = skipped
    session.round_count += 1
    remaining = refresh_progress(session)
    if not remaining:
        session.status = "ready"
        session.step = "ready"
        session.current_dimension = None
        session.current_question = None
    else:
        session.current_question = server_question(session.current_dimension)
    db.add(
        ProfileMessage(
            session_id=session.id,
            role="user",
            content="Prefer not to answer",
            input_mode="text",
            target_dimension=dimension,
            sensitive=True,
            refused=True,
        )
    )
    await db.flush()
    return ApiResponse.ok(serialize_session(session))


@router.post("/sessions/{session_id}/complete", response_model=ApiResponse[ProfileWithRecommendationsResponse])
async def complete_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    session = await owned_session(db, session_id, user.id)
    if session.pending_profile_evidence:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pending profile evidence must be confirmed or rejected before completion",
        )
    minimum_not_reached = session.status not in {"ready", "completed"} and (
        session.round_count < session.min_rounds
        and session.turn_count < session.max_rounds
    )
    if minimum_not_reached or session.status not in {"ready", "completed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Minimum conversation rounds not reached", "required": session.min_rounds},
        )
    existing = await db.scalar(select(InvestmentProfile).where(InvestmentProfile.session_id == session.id))
    if existing is not None:
        return ApiResponse.ok(await completed_profile_response(db, existing))

    previous_versions = (
        await db.scalars(select(InvestmentProfile.version).where(InvestmentProfile.user_id == user.id))
    ).all()
    assessment = assess_profile(
        session.objective_profile,
        session.dimension_scores,
        session.profile_evidence,
        session.skipped_dimensions,
    )
    education_only = session.objective_profile.get("age_range") == "minor"
    profile = InvestmentProfile(
        user_id=user.id,
        session_id=session.id,
        version=max(previous_versions, default=0) + 1,
        objective_profile=session.objective_profile,
        dimension_scores=assessment.dimension_scores,
        profile_evidence=session.profile_evidence,
        archetype_code=assessment.archetype_code,
        archetype_title=assessment.archetype_title,
        risk_level=assessment.risk_level,
        loss_tolerance_percent=assessment.loss_tolerance_percent,
        confidence=round(sum(session.dimension_scores.values()) / max(1, len(session.dimension_scores)), 2),
        completeness=session.completeness,
        education_only=education_only,
        report_summary=assessment.summary,
    )
    db.add(profile)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        existing = await db.scalar(
            select(InvestmentProfile).where(InvestmentProfile.session_id == session_id)
        )
        if existing is not None:
            return ApiResponse.ok(await completed_profile_response(db, existing))
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Investment profile version conflicts with another completion",
        ) from exc
    recommendations = [
        DirectionRecommendation(profile_id=profile.id, **item)
        for item in rank_directions(
            assessment,
            session.objective_profile,
            education_only,
            session.profile_evidence,
        )
    ]
    db.add_all(recommendations)
    session.status = "completed"
    session.step = "report"
    session.current_question = None
    session.live_key = None
    session.completed_at = datetime.now(timezone.utc)
    await db.flush()
    return ApiResponse.ok(
        {"profile": serialize_profile(profile), "recommendations": [serialize_recommendation(item) for item in recommendations]}
    )


def serialize_profile(profile: InvestmentProfile) -> dict:
    return {
        "id": profile.id,
        "user_id": profile.user_id,
        "session_id": profile.session_id,
        "version": profile.version,
        "objective_profile": profile.objective_profile,
        "dimension_scores": profile.dimension_scores,
        "profile_evidence": profile.profile_evidence,
        "archetype_code": profile.archetype_code,
        "archetype_title": profile.archetype_title,
        "risk_level": profile.risk_level,
        "loss_tolerance_percent": profile.loss_tolerance_percent,
        "confidence": profile.confidence,
        "completeness": profile.completeness,
        "education_only": profile.education_only,
        "report_summary": profile.report_summary,
    }


def serialize_recommendation(item: DirectionRecommendation) -> dict:
    return {
        "id": item.id,
        "direction": item.direction,
        "score": item.score,
        "rank": item.rank,
        "reason": item.reason,
        "actionable": item.actionable,
        "selected": item.selected,
    }
