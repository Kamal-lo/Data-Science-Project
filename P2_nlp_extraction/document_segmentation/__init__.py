"""T26 : segmentation des conversions T24, sans OCR ni extraction métier."""
from .api import segment_document, SegmentationLimits, SegmentationInputError

__all__ = ['segment_document', 'SegmentationLimits', 'SegmentationInputError']
