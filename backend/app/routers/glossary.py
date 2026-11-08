"""Glossary endpoints: view and edit the session's term pairs. User edits override model terms."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import get_store
from app.schemas import ErrorResponse, GlossaryEntry, GlossaryResponse, GlossaryUpdate
from app.services.glossary import as_list, replace_with_user_terms
from app.services.session_store import SessionStore

router = APIRouter(prefix="/api/sessions/{session_id}/glossary", tags=["glossary"])


def _response(state: dict) -> GlossaryResponse:
    return GlossaryResponse(
        source_lang=state["source_lang"],
        target_lang=state["target_lang"],
        terms=[GlossaryEntry(**t) for t in as_list(state["glossary"])],
    )


@router.get("", response_model=GlossaryResponse, responses={404: {"model": ErrorResponse}})
def get_glossary(session_id: str, store: SessionStore = Depends(get_store)) -> GlossaryResponse:
    return _response(store.load_state(session_id))


@router.put("", response_model=GlossaryResponse, responses={404: {"model": ErrorResponse}})
def put_glossary(session_id: str, body: GlossaryUpdate, store: SessionStore = Depends(get_store)) -> GlossaryResponse:
    with store.edit_state(session_id) as st:
        st["glossary"] = replace_with_user_terms(st["glossary"], [(t.source, t.target) for t in body.terms])
        out = _response(st)
    return out
