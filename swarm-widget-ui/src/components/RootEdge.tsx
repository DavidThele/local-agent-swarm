import React, { useEffect, useMemo, useState } from 'react';
import { EdgeProps } from '@xyflow/react';

// Tracks edge IDs that have already completed their initial spawn growth animation
const animatedEdgeIds = new Set<string>();

export function clearAnimatedRoots() {
  animatedEdgeIds.clear();
}

function hashString(str: string): number {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function createRng(seed: number) {
  let s = seed || 1;
  return () => {
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

interface BranchTendril {
  d: string;
  delayMs: number;
  width: number;
}

const RootEdgeComponent: React.FC<EdgeProps> = ({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  style,
}) => {
  // Only animate if this edge ID has never finished animating in the current session
  const [isAnimating, setIsAnimating] = useState<boolean>(() => !animatedEdgeIds.has(id));

  useEffect(() => {
    if (!isAnimating) return;
    // Wait until main root (620ms) + slowest tendril finish, then lock static
    const timer = window.setTimeout(() => {
      animatedEdgeIds.add(id);
      setIsAnimating(false);
    }, 950);
    return () => clearTimeout(timer);
  }, [id, isAnimating]);

  const { mainPath, tendrils } = useMemo(() => {
    const rng = createRng(hashString(id));
    const dx = targetX - sourceX;
    const dy = targetY - sourceY;
    const dist = Math.hypot(dx, dy) || 1;

    const perpX = -dy / dist;
    const perpY = dx / dist;

    const segments = 6;
    const pts: { x: number; y: number }[] = [{ x: sourceX, y: sourceY }];

    for (let i = 1; i < segments; i++) {
      const t = i / segments;
      const envelope = Math.sin(t * Math.PI);
      const jitterAlong = (rng() - 0.5) * 0.08;
      const tClamped = Math.max(0.08, Math.min(0.92, t + jitterAlong));

      const maxSwing = Math.min(34, dist * 0.16);
      const lateral = (rng() - 0.5) * 2 * maxSwing * envelope;

      pts.push({
        x: sourceX + dx * tClamped + perpX * lateral,
        y: sourceY + dy * tClamped + perpY * lateral,
      });
    }
    pts.push({ x: targetX, y: targetY });

    const mainD = pts
      .map((p, idx) => `${idx === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
      .join(' ');

    const offshoots: BranchTendril[] = [];
    const jointIndices = [1, 2, 3, 4];

    jointIndices.forEach((jointIdx) => {
      if (rng() > 0.68) return;

      const origin = pts[jointIdx];
      const next = pts[jointIdx + 1];
      const baseAngle = Math.atan2(next.y - origin.y, next.x - origin.x);
      const side = rng() > 0.5 ? 1 : -1;
      const branchAngle = baseAngle + side * (0.45 + rng() * 0.65);

      const seg1Len = 12 + rng() * 14;
      const midX = origin.x + Math.cos(branchAngle) * seg1Len;
      const midY = origin.y + Math.sin(branchAngle) * seg1Len;

      const tipAngle = branchAngle + (rng() - 0.5) * 0.7;
      const seg2Len = 8 + rng() * 12;
      const tipX = midX + Math.cos(tipAngle) * seg2Len;
      const tipY = midY + Math.sin(tipAngle) * seg2Len;

      offshoots.push({
        d: `M ${origin.x.toFixed(1)} ${origin.y.toFixed(1)} L ${midX.toFixed(1)} ${midY.toFixed(
          1
        )} L ${tipX.toFixed(1)} ${tipY.toFixed(1)}`,
        delayMs: Math.round((jointIdx / segments) * 480 + 80),
        width: 1 + rng() * 0.4,
      });
    });

    return { mainPath: mainD, tendrils: offshoots };
  }, [id, sourceX, sourceY, targetX, targetY]);

  const strokeColor = (style?.stroke as string) || '#52525b';
  const strokeWidth = Number(style?.strokeWidth) || 1.75;

  return (
    <g className="pointer-events-none">
      <path
        d={mainPath}
        pathLength={1}
        fill="none"
        stroke={strokeColor}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="bevel"
        className={isAnimating ? 'root-branch-main' : undefined}
      />

      {tendrils.map((tendril, idx) => (
        <path
          key={idx}
          d={tendril.d}
          pathLength={1}
          fill="none"
          stroke={strokeColor}
          strokeOpacity={0.65}
          strokeWidth={tendril.width}
          strokeLinecap="round"
          strokeLinejoin="bevel"
          className={isAnimating ? 'root-branch-tendril' : undefined}
          style={isAnimating ? { animationDelay: `${tendril.delayMs}ms` } : undefined}
        />
      ))}
    </g>
  );
};

export const RootEdge = React.memo(RootEdgeComponent);