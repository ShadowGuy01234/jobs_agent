"""Profile loader and resume parser."""

import logging
from pathlib import Path
from typing import Optional
import yaml
from pypdf import PdfReader

from config import settings
from profile.models import UserProfile

logger = logging.getLogger(__name__)


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract raw text from PDF resume."""
    try:
        reader = PdfReader(str(pdf_path))
        text_chunks = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_chunks.append(text)
        return "\n\n".join(text_chunks)
    except Exception as e:
        logger.warning(f"Failed to extract text from PDF resume {pdf_path}: {e}")
        return ""


def extract_text_from_markdown(md_path: Path) -> str:
    """Extract raw text from Markdown resume."""
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.warning(f"Failed to read Markdown resume {md_path}: {e}")
        return ""


def load_resume_text() -> Optional[str]:
    """Scan profile directory for resume.pdf or resume.md."""
    pdf_resume = settings.PROFILE_DIR / "resume.pdf"
    if pdf_resume.exists():
        extracted = extract_text_from_pdf(pdf_resume)
        if extracted.strip():
            logger.info("Successfully parsed resume from profile/resume.pdf")
            return extracted

    md_resume = settings.PROFILE_DIR / "resume.md"
    if md_resume.exists():
        extracted = extract_text_from_markdown(md_resume)
        if extracted.strip():
            logger.info("Successfully parsed resume from profile/resume.md")
            return extracted

    return None


def load_user_profile(custom_path: Optional[Path] = None) -> UserProfile:
    """Load and validate UserProfile from YAML and optional resume file."""
    profile_file = custom_path or settings.USER_PROFILE_PATH
    if not profile_file.exists():
        raise FileNotFoundError(
            f"user_profile.yaml not found at {profile_file}. Please copy user_profile.yaml template."
        )

    with open(profile_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # Attach parsed resume text if available
    resume_text = load_resume_text()
    if resume_text:
        data["resume_text"] = resume_text

    return UserProfile(**data)
