"""Segmentation: HU thresholding, connected-component region labeling, metal mask."""

from core.segmentation.segment import RegionInfo, SegmentationResult, segment_bone

__all__ = ["RegionInfo", "SegmentationResult", "segment_bone"]
