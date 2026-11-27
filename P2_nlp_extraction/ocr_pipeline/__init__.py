"""API OCR automatique. Les modèles sont chargés dans un processus isolé."""
from .api import OCRPipelineError, extract_pdf

__all__ = ['extract_pdf', 'OCRPipelineError']
