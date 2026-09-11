export interface MentionAnchor {
  top: number;
  bottom: number;
  left: number;
  right: number;
  height: number;
}

export interface MentionPanelLayout {
  bottom: number;
  left: number;
  typeWidth: number;
  resourceWidth: number;
  maxHeight: number;
}

/** Anchor both panes above the composer; CSS intrinsic height grows upward. */
export function layoutMentionPanel(
  anchor: MentionAnchor,
  viewport: { width: number; height: number },
  submenu = false,
): MentionPanelLayout {
  const margin = 8;
  const gap = 8;
  const availableWidth = Math.max(0, viewport.width - margin * 2);
  const typeWidth = Math.min(176, availableWidth, submenu ? availableWidth * 0.4 : 176);
  const resourceWidth = submenu ? Math.min(320, Math.max(0, availableWidth - typeWidth - 4)) : 0;
  const width = typeWidth + (submenu ? resourceWidth + 4 : 0);
  const paneBottom = Math.max(0, Math.min(viewport.height - margin, anchor.top - gap));
  return {
    bottom: viewport.height - paneBottom,
    left: Math.max(margin, Math.min(anchor.left, viewport.width - margin - width)),
    typeWidth,
    resourceWidth,
    maxHeight: Math.max(0, Math.min(320, paneBottom - margin)),
  };
}
