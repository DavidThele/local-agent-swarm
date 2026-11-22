import React, { useEffect, useRef, useState } from 'react';
import { MascotAnimationState } from '../types/swarm';

// ============================================================================
// CUSTOMIZABLE MASCOT KINEMATICS & ANIMATION TIMING CONSTANTS
// ============================================================================
export const MASCOT_CONFIG = {
  // Movement velocities (pixels per second)
  BEZEL_RUN_SPEED_PX_S: 340,
  WALL_CLIMB_SPEED_PX_S: 290,
  CANVAS_RUN_SPEED_PX_S: 360,
  Z_JUMP_SPEED_PX_S: 420,

  // Task Initiation (Acorn Packaging + Z-Depth Arc)
  ACORN_PACKAGE_HOLD_MS: 650,     // Time spent visibly compressing prompt into large acorn
  ACORN_ARC_DURATION_MS: 950,     // Parabolic flight time to squirrel
  ACORN_START_SCALE: 2.35,        // Large foreground scale at input box
  ACORN_END_SCALE: 0.65,          // Small Z-depth scale when caught by squirrel
  ACORN_ARC_APEX_PX: 165,         // Parabolic height lift
  BURY_DURATION_BEFORE_SPAWN_MS: 900, // Digging time before signaling root node spawn

  // Flush Bezel & Resting Offsets (px relative to widget root / elements)
  SPRITE_SIZE_PX: 64,
  LEFT_WALL_FLUSH_X: 0,           // Mathematically flush with left window bezel (x = 0)
  RIGHT_WALL_FLUSH_OFFSET: 64,    // Mathematically flush with right bezel (width - 64)
  INPUT_BOX_TOP_REST_OFFSET_Y: -58, // Sits flush on top edge of text input box

  // Sprite Sheet Row Loop Speeds (CSS duration per frame cycle)
  SPRITE_CYCLE_DURATIONS: {
    '--fps-idle': '0.85s',
    '--fps-run': '0.38s',
    '--fps-climb': '0.42s',
    '--fps-run-canvas': '0.38s',
    '--fps-run-acorn': '0.40s',
    '--fps-jump': '0.32s',
    '--fps-bury': '0.28s',
    '--fps-point': '0.55s',
    '--fps-inspect': '0.70s',
    '--fps-knock': '0.48s',
    '--fps-munch': '0.95s',
  } as React.CSSProperties,
};

interface MascotOverlayProps {
  isMinimized: boolean;
  isCanvasPanning: boolean;
  burySequenceTrigger: number;
  hasRootNode: boolean;
  activeHitlAgentId: string | null;
  failedAgentId: string | null;
  onBuryComplete: (buryClientPos: { x: number; y: number }) => void;
  onInspectFailedNode: (agentId: string) => void;
  onExpandFromKnock: () => void;
}

type SegmentType =
  | 'bezel_run'
  | 'bezel_climb'
  | 'bezel_acorn'
  | 'z_jump'
  | 'canvas_run'
  | 'canvas_acorn';

interface Waypoint {
  x: number;
  y: number;
  segment: SegmentType;
  wallSide?: 'left' | 'right';
}

const TOP_DOWN_ROTATED_STATES = new Set<MascotAnimationState>([
  'running_canvas',
  'running_acorn_canvas',
  'jumping',
]);

function playGlassKnockSound() {
  try {
    const AudioCtx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ctx = new AudioCtx();
    const triggerTap = (delay: number, freq: number) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(freq, ctx.currentTime + delay);
      osc.frequency.exponentialRampToValueAtTime(90, ctx.currentTime + delay + 0.065);
      gain.gain.setValueAtTime(0.16, ctx.currentTime + delay);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + delay + 0.065);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(ctx.currentTime + delay);
      osc.stop(ctx.currentTime + delay + 0.07);
    };
    triggerTap(0, 420);
    triggerTap(0.14, 460);
  } catch {
    // Ignore autoplay restriction prior to interaction
  }
}

export const MascotOverlay: React.FC<MascotOverlayProps> = ({
  isMinimized,
  isCanvasPanning,
  burySequenceTrigger,
  hasRootNode,
  activeHitlAgentId,
  failedAgentId,
  onBuryComplete,
  onInspectFailedNode,
  onExpandFromKnock,
}) => {
  const [pos, setPos] = useState<{ x: number; y: number }>({ x: 380, y: 560 });
  const [animState, setAnimState] = useState<MascotAnimationState>('munching');
  const [flipX, setFlipX] = useState<boolean>(false);
  const [rotationDeg, setRotationDeg] = useState<number>(0);
  const [acornImgError, setAcornImgError] = useState<boolean>(false);

  // Acorn Packaging + Simulated Z-Depth State
  const [acornProjectile, setAcornProjectile] = useState<{
    visible: boolean;
    x: number;
    y: number;
    scale: number;
    packaging: boolean;
  }>({ visible: false, x: 0, y: 0, scale: 1, packaging: false });

  const [dirtMoundCoord, setDirtMoundCoord] = useState<{ x: number; y: number } | null>(null);

  // Mutable Physics Refs for RAF Loop
  const posRef = useRef<{ x: number; y: number }>({ x: 380, y: 560 });
  const waypointsRef = useRef<Waypoint[]>([]);
  const lastTargetKeyRef = useRef<string>('home_rest');
  const wasPanningRef = useRef<boolean>(false);
  const isAcornSequenceActiveRef = useRef<boolean>(false);
  const isWaitingForRootNodeRef = useRef<boolean>(false);
  const lastBuryTriggerRef = useRef<number>(burySequenceTrigger);

  // Helper: Measure Widget, Canvas, and Input Dock Coordinates
  const getLayoutMetrics = () => {
    const rootEl = document.getElementById('swarm-widget-root');
    const canvasEl = document.getElementById('swarm-canvas-viewport');
    const inputEl = document.querySelector('[data-mascot-target="task-input-box"]');

    const rootRect = rootEl?.getBoundingClientRect() || new DOMRect(0, 0, 920, 680);
    const canvasRect = canvasEl?.getBoundingClientRect() || rootRect;
    const inputRect = inputEl?.getBoundingClientRect();

    const canvasRel = {
      left: canvasRect.left - rootRect.left,
      top: canvasRect.top - rootRect.top,
      right: canvasRect.right - rootRect.left - MASCOT_CONFIG.SPRITE_SIZE_PX,
      bottom: canvasRect.bottom - rootRect.top - MASCOT_CONFIG.SPRITE_SIZE_PX,
      width: canvasRect.width,
      height: canvasRect.height,
    };

    // Default Resting Spot (Home): Sitting directly on top of the text input box
    const homeX = inputRect
      ? inputRect.left - rootRect.left + inputRect.width * 0.72
      : canvasRel.left + canvasRel.width * 0.7;
    const homeY = inputRect
      ? inputRect.top - rootRect.top + MASCOT_CONFIG.INPUT_BOX_TOP_REST_OFFSET_Y
      : rootRect.height - 108;

    const inputCenterX = inputRect
      ? inputRect.left - rootRect.left + inputRect.width * 0.42
      : canvasRel.left + canvasRel.width * 0.45;
    const inputCenterY = inputRect
      ? inputRect.top - rootRect.top + inputRect.height * 0.5 - 16
      : rootRect.height - 46;

    return { rootRect, canvasRel, homeX, homeY, inputCenterX, inputCenterY };
  };

  // Helper: Build Flush Border-to-Canvas Waypoints (Bezel -> Wall Climb -> Z-Jump -> Canvas)
  const buildFlushBorderToCanvasPath = (
    _startX: number,
    startY: number,
    destX: number,
    destY: number,
    carryingAcorn: boolean
  ): Waypoint[] => {
    const { canvasRel } = getLayoutMetrics();
    const leftWallX = canvasRel.left + MASCOT_CONFIG.LEFT_WALL_FLUSH_X;
    const rightWallX =
      canvasRel.left + canvasRel.width - MASCOT_CONFIG.RIGHT_WALL_FLUSH_OFFSET;

    const useLeftWall =
      Math.abs(destX - leftWallX) <= Math.abs(destX - rightWallX);
    const wallX = useLeftWall ? leftWallX : rightWallX;
    const wallSide: 'left' | 'right' = useLeftWall ? 'left' : 'right';
    const jumpIntoCanvasOffsetX = useLeftWall ? wallX + 36 : wallX - 36;

    return [
      {
        x: wallX,
        y: startY,
        segment: carryingAcorn ? 'bezel_acorn' : 'bezel_run',
      },
      {
        x: wallX,
        y: destY,
        segment: 'bezel_climb',
        wallSide,
      },
      {
        x: jumpIntoCanvasOffsetX,
        y: destY,
        segment: 'z_jump',
      },
      {
        x: destX,
        y: destY,
        segment: carryingAcorn ? 'canvas_acorn' : 'canvas_run',
      },
    ];
  };

  // Snap to Home on Initial Mount in `munching` state
  useEffect(() => {
    const { homeX, homeY } = getLayoutMetrics();
    posRef.current = { x: homeX, y: homeY };
    setPos({ x: homeX, y: homeY });
    setAnimState('munching');
  }, []);

  // =========================================================================
  // 1. TASK INITIATION: SWITCH TO `idle` -> PACKAGING + Z-DEPTH ARC -> BURROW
  // =========================================================================
  useEffect(() => {
    if (burySequenceTrigger <= lastBuryTriggerRef.current) return;
    lastBuryTriggerRef.current = burySequenceTrigger;

    isAcornSequenceActiveRef.current = true;
    isWaitingForRootNodeRef.current = false;
    waypointsRef.current = [];

    const { canvasRel, homeX, homeY, inputCenterX, inputCenterY } = getLayoutMetrics();

    // Switch from `munching` to `idle` to wait for the thrown acorn
    posRef.current = { x: homeX, y: homeY };
    setPos({ x: homeX, y: homeY });
    setRotationDeg(0);
    setAnimState('idle');
    setFlipX(true); // Face left toward the incoming acorn from input center

    const digCenterX = canvasRel.left + canvasRel.width * 0.44;
    const digCenterY = canvasRel.top + 85;

    const seqStart = performance.now();
    const holdMs = MASCOT_CONFIG.ACORN_PACKAGE_HOLD_MS;
    const arcMs = MASCOT_CONFIG.ACORN_ARC_DURATION_MS;

    const stepAcornFlight = (now: number) => {
      const elapsed = now - seqStart;

      // Phase A: Visible Prompt-to-Acorn Packaging at large foreground scale
      if (elapsed < holdMs) {
        const pulseT = elapsed / holdMs;
        const pulseScale =
          MASCOT_CONFIG.ACORN_START_SCALE * (0.85 + 0.15 * Math.sin(pulseT * Math.PI));
        setAcornProjectile({
          visible: true,
          x: inputCenterX,
          y: inputCenterY,
          scale: pulseScale,
          packaging: true,
        });
        requestAnimationFrame(stepAcornFlight);
        return;
      }

      // Phase B: Parabolic Arc with Simulated Z-Depth Scale-Down
      const arcElapsed = elapsed - holdMs;
      const t = Math.min(1, arcElapsed / arcMs);

      const curX = inputCenterX + (homeX + 16 - inputCenterX) * t;
      const linearY = inputCenterY + (homeY + 12 - inputCenterY) * t;
      const parabolaLift = -MASCOT_CONFIG.ACORN_ARC_APEX_PX * 4 * t * (1 - t);
      const curScale =
        MASCOT_CONFIG.ACORN_START_SCALE +
        (MASCOT_CONFIG.ACORN_END_SCALE - MASCOT_CONFIG.ACORN_START_SCALE) * t;

      setAcornProjectile({
        visible: true,
        x: curX,
        y: linearY + parabolaLift,
        scale: curScale,
        packaging: false,
      });

      if (t < 1) {
        requestAnimationFrame(stepAcornFlight);
      } else {
        // Phase C: Caught! Route flush along bezel -> climb wall -> jump -> run with acorn on canvas
        setAcornProjectile({ visible: false, x: 0, y: 0, scale: 1, packaging: false });
        waypointsRef.current = buildFlushBorderToCanvasPath(
          posRef.current.x,
          posRef.current.y,
          digCenterX,
          digCenterY,
          true
        );
      }
    };

    requestAnimationFrame(stepAcornFlight);
  }, [burySequenceTrigger]);

  // =========================================================================
  // 2. IMMEDIATE BURROWING STOP WHEN ROOT ORCHESTRATOR NODE APPEARS
  // =========================================================================
  useEffect(() => {
    if (hasRootNode && isWaitingForRootNodeRef.current) {
      isWaitingForRootNodeRef.current = false;
      isAcornSequenceActiveRef.current = false;
      setDirtMoundCoord(null);

      // Immediately stop `burying` and route back to resting spot on top of the input box
      const { homeX, homeY } = getLayoutMetrics();
      lastTargetKeyRef.current = 'home_rest';
      waypointsRef.current = [
        { x: homeX, y: homeY, segment: 'canvas_run' },
      ];
    }
  }, [hasRootNode]);

  // =========================================================================
  // 3. TARGET RESOLUTION & AUTOMATIC RETURN TO INPUT BOX RESTING SPOT
  // =========================================================================
  useEffect(() => {
    const interval = window.setInterval(() => {
      if (isAcornSequenceActiveRef.current || isWaitingForRootNodeRef.current) return;

      // Minimized Peekaboo State: Sit flush on top of the slim progress bar
      if (isMinimized) {
        waypointsRef.current = [];
        const targetX = 148;
        const targetY = -56;
        posRef.current = { x: targetX, y: targetY };
        setPos({ x: targetX, y: targetY });
        setRotationDeg(0);
        setFlipX(false);
        setAnimState(activeHitlAgentId || failedAgentId ? 'knocking' : 'munching');
        return;
      }

      // Screen-Space Panning Lock: Freeze Byte on the glass while user drags the canvas
      if (isCanvasPanning) {
        wasPanningRef.current = true;
        waypointsRef.current = [];
        return;
      }

      const { rootRect, canvasRel, homeX, homeY } = getLayoutMetrics();
      const targetAgentId = failedAgentId || activeHitlAgentId;

      // No active blockers/faults -> Route back to Resting Spot and munch
      if (!targetAgentId) {
        if (lastTargetKeyRef.current !== 'home_rest' && waypointsRef.current.length === 0) {
          lastTargetKeyRef.current = 'home_rest';
          const distHome = Math.hypot(homeX - posRef.current.x, homeY - posRef.current.y);
          if (distHome > 8) {
            const leftWallX = canvasRel.left + MASCOT_CONFIG.LEFT_WALL_FLUSH_X;
            const rightWallX =
              canvasRel.left + canvasRel.width - MASCOT_CONFIG.RIGHT_WALL_FLUSH_OFFSET;
            const useLeftWall =
              Math.abs(posRef.current.x - leftWallX) <=
              Math.abs(posRef.current.x - rightWallX);
            const wallX = useLeftWall ? leftWallX : rightWallX;

            waypointsRef.current = [
              { x: wallX, y: posRef.current.y, segment: 'canvas_run' },
              {
                x: wallX,
                y: homeY,
                segment: 'bezel_climb',
                wallSide: useLeftWall ? 'left' : 'right',
              },
              { x: homeX, y: homeY, segment: 'bezel_run' },
            ];
          } else {
            setAnimState('munching');
            setRotationDeg(0);
          }
        }
        return;
      }

      // Locate Target DOM Node or HITL Card
      const nodeEl =
        document.querySelector(`[data-agent-node="${targetAgentId}"]`) ||
        document.querySelector('[data-mascot-target="hitl-action-box"]');

      if (!nodeEl) return;

      const nodeRect = nodeEl.getBoundingClientRect();
      const rawX = nodeRect.left - rootRect.left + nodeRect.width * 0.5 - 32;
      const rawY = nodeRect.top - rootRect.top - 42;

      const isOffScreen =
        rawX < canvasRel.left ||
        rawX > canvasRel.right ||
        rawY < canvasRel.top ||
        rawY > canvasRel.bottom;

      const clampedX = Math.max(canvasRel.left + 4, Math.min(canvasRel.right - 4, rawX));
      const clampedY = Math.max(canvasRel.top + 4, Math.min(canvasRel.bottom - 4, rawY));

      const targetKey = `${targetAgentId}_${Math.round(clampedX / 8)}_${Math.round(
        clampedY / 8
      )}_${isOffScreen ? 'off' : 'in'}`;

      if (wasPanningRef.current) {
        wasPanningRef.current = false;
        lastTargetKeyRef.current = targetKey;
        waypointsRef.current = [
          {
            x: clampedX,
            y: clampedY,
            segment: 'canvas_run',
          },
        ];
        return;
      }

      if (lastTargetKeyRef.current !== targetKey && waypointsRef.current.length === 0) {
        lastTargetKeyRef.current = targetKey;
        const dist = Math.hypot(clampedX - posRef.current.x, clampedY - posRef.current.y);
        if (dist < 10) return;

        const isAtBottomRest = Math.abs(posRef.current.y - homeY) < 28;
        if (isAtBottomRest && !isOffScreen) {
          waypointsRef.current = buildFlushBorderToCanvasPath(
            posRef.current.x,
            posRef.current.y,
            clampedX,
            clampedY,
            false
          );
        } else {
          waypointsRef.current = [
            { x: clampedX, y: clampedY, segment: 'canvas_run' },
          ];
        }
      }
    }, 80);

    return () => clearInterval(interval);
  }, [isMinimized, isCanvasPanning, activeHitlAgentId, failedAgentId]);

  // =========================================================================
  // 4. LINEAR KINEMATICS & VELOCITY-VECTOR ROTATION / FLIP ENGINE
  // =========================================================================
  useEffect(() => {
    let lastTime = performance.now();
    let rafId: number;

    const stepPhysics = (now: number) => {
      const dt = Math.min(0.05, (now - lastTime) / 1000);
      lastTime = now;

      if (!isMinimized && !isCanvasPanning && waypointsRef.current.length > 0) {
        const wp = waypointsRef.current[0];
        const dx = wp.x - posRef.current.x;
        const dy = wp.y - posRef.current.y;
        const dist = Math.hypot(dx, dy);

        const speed =
          wp.segment === 'bezel_climb'
            ? MASCOT_CONFIG.WALL_CLIMB_SPEED_PX_S
            : wp.segment === 'z_jump'
            ? MASCOT_CONFIG.Z_JUMP_SPEED_PX_S
            : wp.segment === 'canvas_run' || wp.segment === 'canvas_acorn'
            ? MASCOT_CONFIG.CANVAS_RUN_SPEED_PX_S
            : MASCOT_CONFIG.BEZEL_RUN_SPEED_PX_S;

        const stepDist = speed * dt;

        if (wp.segment === 'canvas_run' || wp.segment === 'canvas_acorn' || wp.segment === 'z_jump') {
          const nextState: MascotAnimationState =
            wp.segment === 'z_jump'
              ? 'jumping'
              : wp.segment === 'canvas_acorn'
              ? 'running_acorn_canvas'
              : 'running_canvas';
          setAnimState(nextState);
          setFlipX(false);

          if (dist > 0.5) {
            const angleDeg = (Math.atan2(dy, dx) * 180) / Math.PI - 90;
            setRotationDeg(angleDeg);
          }
        } else if (wp.segment === 'bezel_climb') {
          setAnimState('climbing');
          setRotationDeg(0);
          setFlipX(wp.wallSide === 'left');
        } else {
          setAnimState(wp.segment === 'bezel_acorn' ? 'running_acorn_bezel' : 'running');
          setRotationDeg(0);
          if (Math.abs(dx) > 0.5) {
            setFlipX(dx < 0);
          }
        }

        if (dist <= stepDist) {
          posRef.current = { x: wp.x, y: wp.y };
          setPos({ x: wp.x, y: wp.y });
          waypointsRef.current.shift();

          if (waypointsRef.current.length === 0) {
            setRotationDeg(0);

            if (isAcornSequenceActiveRef.current) {
              setAnimState('burying');
              setFlipX(false);

              const moundRelX = wp.x + 32;
              const moundRelY = wp.y + 48;
              setDirtMoundCoord({ x: moundRelX, y: moundRelY });
              isWaitingForRootNodeRef.current = true;

              const { rootRect } = getLayoutMetrics();
              const buryClientPos = {
                x: rootRect.left + moundRelX,
                y: rootRect.top + moundRelY,
              };

              setTimeout(() => {
                onBuryComplete(buryClientPos);
              }, MASCOT_CONFIG.BURY_DURATION_BEFORE_SPAWN_MS);
            } else if (failedAgentId) {
              setAnimState('inspecting');
            } else if (activeHitlAgentId) {
              setAnimState('pointing');
            } else {
              // Back at resting spot with nothing to do -> munch on an acorn
              setAnimState('munching');
            }
          }
        } else {
          const vx = (dx / dist) * stepDist;
          const vy = (dy / dist) * stepDist;
          posRef.current = { x: posRef.current.x + vx, y: posRef.current.y + vy };
          setPos({ ...posRef.current });
        }
      }

      rafId = requestAnimationFrame(stepPhysics);
    };

    rafId = requestAnimationFrame(stepPhysics);
    return () => cancelAnimationFrame(rafId);
  }, [isMinimized, isCanvasPanning, failedAgentId, activeHitlAgentId, onBuryComplete]);

  // Periodic Glass Knock Sound in Minimized Alert Mode
  useEffect(() => {
    if (isMinimized && animState === 'knocking') {
      playGlassKnockSound();
      const id = window.setInterval(playGlassKnockSound, 2200);
      return () => clearInterval(id);
    }
  }, [isMinimized, animState]);

  const isClickable =
    (animState === 'inspecting' && failedAgentId) || isMinimized;

  const spriteTransform = TOP_DOWN_ROTATED_STATES.has(animState)
    ? `translate3d(${Math.round(pos.x)}px, ${Math.round(pos.y)}px, 0) rotate(${Math.round(
        rotationDeg
      )}deg)`
    : `translate3d(${Math.round(pos.x)}px, ${Math.round(pos.y)}px, 0) scaleX(${
        flipX ? -1 : 1
      })`;

  return (
    <div
      style={MASCOT_CONFIG.SPRITE_CYCLE_DURATIONS}
      className="pointer-events-none absolute inset-0 z-50 overflow-visible"
    >
      {/* Acorn Projectile: Uses public/sprites/acorn.png with Z-Depth Scaling */}
      {acornProjectile.visible && (
        <div
          className="absolute z-50 origin-center"
          style={{
            transform: `translate3d(${Math.round(acornProjectile.x)}px, ${Math.round(
              acornProjectile.y
            )}px, 0) scale(${acornProjectile.scale.toFixed(2)})`,
          }}
        >
          {!acornImgError ? (
            <img
              src="/sprites/acorn.png"
              alt="Acorn"
              onError={() => setAcornImgError(true)}
              style={{ imageRendering: 'pixelated' }}
              className="h-8 w-8 object-contain select-none"
              draggable={false}
            />
          ) : (
            <svg width="24" height="24" viewBox="0 0 16 16" fill="none">
              <path d="M3 6C3 3.5 5.5 2 8 2C10.5 2 13 3.5 13 6H3Z" fill="#71717A" />
              <rect x="7" y="0" width="2" height="2" fill="#E4E4E7" />
              <path d="M4 6H12L10.5 13L8 15L5.5 13L4 6Z" fill="#FF6B00" />
            </svg>
          )}
        </div>
      )}

      {/* Dirt Mound while Burying Acorn at Canvas Center */}
      {dirtMoundCoord && (
        <div
          className="absolute z-40 flex -translate-x-1/2 -translate-y-1/2 items-center justify-center"
          style={{
            left: `${Math.round(dirtMoundCoord.x)}px`,
            top: `${Math.round(dirtMoundCoord.y)}px`,
          }}
        >
          <div className="h-3 w-8 rounded-full bg-[#FF6B00]/40 blur-[2px] animate-ping" />
          <div className="absolute h-2 w-6 rounded-full border border-[#FF6B00] bg-zinc-800" />
        </div>
      )}

      {/* 12-Row Custom Sprite Sheet Element */}
      <div
        onClick={() => {
          if (isMinimized) {
            onExpandFromKnock();
          } else if (failedAgentId && animState === 'inspecting') {
            onInspectFailedNode(failedAgentId);
          }
        }}
        style={{ transform: spriteTransform }}
        className={`byte-sprite has-custom-spritesheet ${
          isClickable ? 'pointer-events-auto cursor-pointer' : 'pointer-events-none'
        }`}
        data-state={animState}
      />
    </div>
  );
};