"""User-facing errors. Every error response is JSON with a friendly bilingual message."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """An error safe to show to the user.

    `code` is a stable machine-readable identifier the frontend can switch on;
    `message` / `message_hi` are friendly English / Hindi texts.
    """

    def __init__(self, status_code: int, code: str, message: str, message_hi: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.message_hi = message_hi
        self.headers: dict[str, str] = {}

    def to_dict(self) -> dict[str, str]:
        return {"error": self.code, "message": self.message, "message_hi": self.message_hi}


# --- Upload / validation errors -------------------------------------------------------------

def not_pdf() -> AppError:
    return AppError(
        400, "not_pdf",
        "This file is not a PDF or a photo. Please upload a PDF, or photos of the pages (JPG/PNG).",
        "यह फ़ाइल PDF या फ़ोटो नहीं है। कृपया PDF या पृष्ठों की फ़ोटो (JPG/PNG) अपलोड करें।",
    )


def unsupported_file() -> AppError:
    return AppError(
        400, "unsupported_file",
        "Please upload a PDF, or photos of the pages (JPG, PNG or WebP).",
        "कृपया PDF या पृष्ठों की फ़ोटो (JPG, PNG या WebP) अपलोड करें।",
    )


def ocr_unavailable() -> AppError:
    return AppError(
        400, "scanned_pdf",
        "This looks like a scanned book or photo. Reading scans needs the AI translation service, "
        "which is not set up on this server.",
        "यह स्कैन की गई किताब या फ़ोटो लगती है। स्कैन पढ़ने के लिए AI अनुवाद सेवा चाहिए, जो इस सर्वर पर सेट नहीं है।",
    )


def corrupt_pdf() -> AppError:
    return AppError(
        400, "corrupt_pdf",
        "We could not open this PDF. It may be damaged.",
        "यह PDF खोली नहीं जा सकी। फ़ाइल ख़राब हो सकती है।",
    )


def encrypted_pdf() -> AppError:
    return AppError(
        400, "encrypted_pdf",
        "This PDF is password-protected. Please upload an unlocked PDF.",
        "यह PDF पासवर्ड से सुरक्षित है। कृपया बिना पासवर्ड वाली PDF अपलोड करें।",
    )


def too_large(max_mb: int) -> AppError:
    return AppError(
        413, "file_too_large",
        f"This file is too big. The maximum size is {max_mb} MB.",
        f"फ़ाइल बहुत बड़ी है। अधिकतम आकार {max_mb} MB है।",
    )


def too_many_pages(pages: int, max_pages: int) -> AppError:
    return AppError(
        400, "too_many_pages",
        f"This PDF has {pages} pages. The maximum is {max_pages} pages.",
        f"इस PDF में {pages} पृष्ठ हैं। अधिकतम {max_pages} पृष्ठ की अनुमति है।",
    )


def empty_pdf() -> AppError:
    return AppError(
        400, "empty_pdf",
        "This PDF has no pages.",
        "इस PDF में कोई पृष्ठ नहीं है।",
    )


def scanned_pdf() -> AppError:
    return AppError(
        400, "scanned_pdf",
        "This looks like a scanned PDF. Only original digital PDFs are supported right now.",
        "यह स्कैन की गई PDF लगती है। अभी केवल मूल डिजिटल PDF ही समर्थित हैं।",
    )


def legacy_font(fonts: list[str]) -> AppError:
    names = f" ({', '.join(fonts[:3])})" if fonts else ""
    return AppError(
        400, "legacy_font",
        "This Hindi PDF uses an old non-Unicode font" + names + ", such as Kruti Dev or Chanakya. "
        "Its text cannot be read correctly yet. Please try a PDF that uses Unicode Hindi fonts.",
        "यह हिंदी PDF पुराने नॉन-यूनिकोड फ़ॉन्ट (जैसे कृतिदेव या चाणक्य) में है। "
        "इसका पाठ अभी सही से पढ़ा नहीं जा सकता। कृपया यूनिकोड हिंदी फ़ॉन्ट वाली PDF आज़माएँ।",
    )


def unreadable_encoding() -> AppError:
    return AppError(
        400, "unreadable_text",
        "The text in this PDF cannot be extracted correctly (custom font encoding).",
        "इस PDF का पाठ सही से निकाला नहीं जा सकता (असामान्य फ़ॉन्ट एन्कोडिंग)।",
    )


def unsupported_language() -> AppError:
    return AppError(
        400, "unsupported_language",
        "We could not find Hindi or English text in this PDF.",
        "इस PDF में हिंदी या अंग्रेज़ी पाठ नहीं मिला।",
    )


def session_not_found() -> AppError:
    return AppError(
        404, "session_not_found",
        "This session has expired or does not exist. Please upload the book again.",
        "यह सत्र समाप्त हो गया है या मौजूद नहीं है। कृपया किताब फिर से अपलोड करें।",
    )


def invalid_chapters(message: str, message_hi: str) -> AppError:
    return AppError(400, "invalid_chapters", message, message_hi)


def translation_started() -> AppError:
    return AppError(
        409, "translation_started",
        "Chapters and language can only be changed before the first translation starts.",
        "अध्याय और भाषा केवल पहला अनुवाद शुरू होने से पहले ही बदली जा सकती हैं।",
    )


def chapter_not_found() -> AppError:
    return AppError(404, "chapter_not_found", "This chapter does not exist.", "यह अध्याय मौजूद नहीं है।")


def paragraph_not_found() -> AppError:
    return AppError(404, "paragraph_not_found", "This paragraph does not exist.", "यह अनुच्छेद मौजूद नहीं है।")


def job_not_found() -> AppError:
    return AppError(
        404, "job_not_found",
        "This translation job was not found. It may have finished long ago or the server restarted.",
        "यह अनुवाद कार्य नहीं मिला। शायद यह बहुत पहले पूरा हो गया या सर्वर फिर से शुरू हुआ।",
    )


def job_running() -> AppError:
    return AppError(
        409, "job_running",
        "Another chapter is being translated right now. Please wait for it to finish.",
        "अभी एक और अध्याय का अनुवाद चल रहा है। कृपया उसके पूरा होने की प्रतीक्षा करें।",
    )


def chapter_wrong_status(action: str, status: str) -> AppError:
    return AppError(
        409, "chapter_wrong_status",
        f"You cannot {action} this chapter while it is '{status}'.",
        f"अध्याय की वर्तमान स्थिति ('{status}') में यह कार्य नहीं किया जा सकता।",
    )


def untranslated_paragraphs(count: int) -> AppError:
    return AppError(
        409, "untranslated_paragraphs",
        f"{count} paragraph(s) are not translated yet. Re-translate or edit them before approving.",
        f"{count} अनुच्छेद का अनुवाद अभी बाकी है। स्वीकृत करने से पहले उन्हें फिर से अनुवाद या संपादित करें।",
    )


def invalid_paragraphs(message: str) -> AppError:
    return AppError(400, "invalid_paragraphs", message, "चुने गए अनुच्छेद मान्य नहीं हैं।")


def translator_not_configured(detail: str) -> AppError:
    return AppError(
        503, "translator_not_configured",
        f"The translation service is not set up on the server ({detail}).",
        "सर्वर पर अनुवाद सेवा सेट नहीं है।",
    )


def pdf_unavailable() -> AppError:
    return AppError(
        503, "pdf_unavailable",
        "PDF creation is not available on the server (WeasyPrint system libraries are missing).",
        "सर्वर पर PDF बनाने की सुविधा उपलब्ध नहीं है।",
    )


def preview_not_ready() -> AppError:
    return AppError(
        404, "preview_not_ready",
        "This preview page is not available. Please open the preview again.",
        "यह पूर्वावलोकन पृष्ठ उपलब्ध नहीं है। कृपया पूर्वावलोकन फिर से खोलें।",
    )


def no_approved_chapters() -> AppError:
    return AppError(
        409, "no_approved_chapters",
        "No chapters are approved yet. Approve at least one chapter to download the book.",
        "अभी कोई अध्याय स्वीकृत नहीं है। किताब डाउनलोड करने के लिए कम से कम एक अध्याय स्वीकृत करें।",
    )


async def app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return JSONResponse(status_code=exc.status_code, content=exc.to_dict(), headers=exc.headers or None)
