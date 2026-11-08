from __future__ import annotations

from functools import lru_cache

from fastapi import Depends

from app import errors
from app.config import Settings, get_settings
from app.services.session_store import SessionStore
from app.services.translator import get_translator
from app.services.translator.base import Translator, TranslatorConfigError


@lru_cache
def get_store() -> SessionStore:
    return SessionStore(get_settings().sessions_dir)


def get_translator_dep(settings: Settings = Depends(get_settings)) -> Translator:
    try:
        return get_translator(settings)
    except TranslatorConfigError as e:
        raise errors.translator_not_configured(str(e)) from None
