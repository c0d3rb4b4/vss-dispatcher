"""Image composition for overlaying images on base images."""

import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

from PIL import Image

logger = logging.getLogger(__name__)


class ImageCompositor:
    """Handles image composition and base image management."""

    def __init__(
        self,
        base_image_dir: str,
        composite_dir: str,
        display_width: int = 2560,
        display_height: int = 1440,
    ):
        """Initialize image compositor.

        Args:
            base_image_dir: Directory to store current base image
            composite_dir: Directory to store composited images
            display_width: Display width in pixels
            display_height: Display height in pixels
        """
        self.base_image_dir = Path(base_image_dir)
        self.composite_dir = Path(composite_dir)
        self.display_width = display_width
        self.display_height = display_height
        self._current_base_path = self.base_image_dir / "current.png"

        # Create directories
        self.base_image_dir.mkdir(parents=True, exist_ok=True)
        self.composite_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(
            "Compositor initialized: base_dir=%s, composite_dir=%s, resolution=%dx%d",
            self.base_image_dir, self.composite_dir, display_width, display_height
        )

    def get_current_base_image_path(self) -> str:
        """Get the path to the current base image.
        
        Returns:
            String path to current base image
        """
        return str(self._current_base_path)

    def get_current_base_image(self) -> Image.Image:
        """Get the current base image.

        If no base image exists, creates a white background.

        Returns:
            PIL Image object
        """
        if self._current_base_path.exists():
            try:
                logger.debug("Loading existing base image: %s", self._current_base_path)
                return Image.open(self._current_base_path)
            except Exception as e:
                logger.error("Failed to load base image: %s, error=%s", self._current_base_path, str(e))
                # Fall through to create default

        logger.info("Creating default white base image: %dx%d", self.display_width, self.display_height)
        base_image = Image.new("RGB", (self.display_width, self.display_height), "white")
        
        # Save it for future use
        try:
            base_image.save(self._current_base_path)
            logger.debug("Saved default base image: %s", self._current_base_path)
        except Exception as e:
            logger.error("Failed to save default base image: %s, error=%s", self._current_base_path, str(e))

        return base_image

    def update_base_image(self, image_path: str) -> bool:
        """Update the current base image.

        Args:
            image_path: Path to new base image

        Returns:
            True if successful, False otherwise
        """
        try:
            logger.debug("Updating base image from: %s", image_path)
            
            # Load and resize if needed
            new_base = Image.open(image_path)
            if new_base.size != (self.display_width, self.display_height):
                logger.debug(
                    "Resizing base image: %dx%d -> %dx%d",
                    new_base.width, new_base.height,
                    self.display_width, self.display_height
                )
                new_base = new_base.resize((self.display_width, self.display_height), Image.Resampling.LANCZOS)

            # Convert to RGB if needed
            if new_base.mode != "RGB":
                logger.debug("Converting base image to RGB from mode: %s", new_base.mode)
                new_base = new_base.convert("RGB")

            # Save as current base
            new_base.save(self._current_base_path)
            logger.info("Base image updated successfully: %s", self._current_base_path)
            return True

        except Exception as e:
            logger.error("Failed to update base image: image=%s, error=%s", image_path, str(e), exc_info=True)
            return False

    def composite_overlay(self, overlay_path: str) -> Optional[str]:
        """Composite an overlay on the current base image at bottom-right corner.

        Args:
            overlay_path: Path to overlay image (should be transparent PNG)

        Returns:
            Path to composited image, or None on failure
        """
        try:
            logger.debug("Compositing overlay: %s", overlay_path)
            
            # Load base and overlay
            base = self.get_current_base_image()
            overlay = Image.open(overlay_path)

            # Ensure overlay has alpha channel
            if overlay.mode != "RGBA":
                logger.debug("Converting overlay to RGBA from mode: %s", overlay.mode)
                overlay = overlay.convert("RGBA")

            # Keep overlay at its original size (don't resize to full display)
            overlay_width, overlay_height = overlay.size
            logger.debug("Overlay dimensions: %dx%d", overlay_width, overlay_height)

            # Convert base to RGBA for compositing
            if base.mode != "RGBA":
                base = base.convert("RGBA")

            # Calculate bottom-right position
            x_position = self.display_width - overlay_width
            y_position = self.display_height - overlay_height
            
            logger.debug("Positioning overlay at bottom-right: x=%d, y=%d", x_position, y_position)

            # Paste overlay at bottom-right corner using alpha channel as mask
            base.paste(overlay, (x_position, y_position), overlay)

            # Convert back to RGB for saving
            composited = base.convert("RGB")

            # Generate unique filename based on overlay path
            overlay_hash = hashlib.md5(overlay_path.encode()).hexdigest()[:8]
            output_filename = f"composite_{overlay_hash}.jpg"
            output_path = self.composite_dir / output_filename

            # Save composited image
            composited.save(output_path, "JPEG", quality=95)
            logger.info("Overlay composited successfully: overlay=%s, output=%s", overlay_path, output_path)
            
            return str(output_path)

        except Exception as e:
            logger.error("Failed to composite overlay: overlay=%s, error=%s", overlay_path, str(e), exc_info=True)
            return None

    def clear_old_composites(self, keep_count: int = 10) -> None:
        """Clean up old composite images.

        Args:
            keep_count: Number of recent composites to keep
        """
        try:
            composites = sorted(
                self.composite_dir.glob("composite_*.jpg"),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            
            if len(composites) > keep_count:
                to_delete = composites[keep_count:]
                for composite in to_delete:
                    composite.unlink()
                    logger.debug("Deleted old composite: %s", composite)
                
                logger.info("Cleaned up %d old composites, kept %d", len(to_delete), keep_count)
        
        except Exception as e:
            logger.error("Failed to clean up composites: error=%s", str(e))
