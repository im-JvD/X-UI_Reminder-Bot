"""
Text processing utilities.
"""
import html


def safe_text(text: str | None) -> str:
    """
    Escape HTML special characters for safe Telegram message display.
    
    Args:
        text: Input text
        
    Returns:
        HTML-escaped text safe for Telegram
    """
    if text is None:
        return ""
    
    text = str(text)
    
    return html.escape(text)
    
    
def truncate_text(text: str, max_length: int = 50) -> str:
    """Truncate text with ellipsis if too long"""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."


def clean_email(email: str) -> str:
    """Clean and normalize email/username"""
    return email.strip().lower()
