import React, { useEffect, useRef, useState } from 'react';
import { MascotAnimationState } from '../types/swarm';

interface MascotOverlayProps {
  isMinimized: boolean;
  isCanvasPanning: boolean;
  burySequenceTrigger: number;
  activeHitlAgentId: string | null;
  failedAgentId: string | null;
  onBuryComplete: () => void;
  onInspectFailedNode: (agentId: string) => void;
  onExpandFromKnock: () => void;
}

interface Waypoint {
  x: number;
  y: number;
  mode: 'bezel' | 'top_down';
}

const LINEAR_SPEED_PX_PER_SEC = 360; // Constant moderate velocity, instantaneous start/stop

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
    // Ignore autoplay restriction before user gesture
  }
}

export const MascotOverlay: React.FC<MascotOverlayProps> = ({
  isMinimized,
  isCanvasPanning,
  burySequenceTrigger,
  activeHitlAgentId,
  failedAgentId,
  onBuryComplete,
  onInspectFailedNode,
  onExpandFromKnock,
}) => {
  const [pos, setPos] = useState<{ x: number; y: number }>({ x: 820, y: 6 });
  const [animState, setAnimState] = useState<MascotAnimationState>('idle');
  const [flipX, setFlipX] = useState(false);

  // Acorn Projectile & Bury State
  const [acornProjectile, setAcornProjectile] = useState<{
    visible: boolean;
    x: number;
    y: number;
  }>({ visible: false, x: 0, y: 0 });
  const [dirtMoundCoord, setDirtMoundCoord] = useState<{ x: number; y: number } | null>(null);

  // Mutable Physics Refs for the RAF loop
  const posRef = useRef<{ x: number; y: number }>({ x: 820, y: 6 });
  const waypointsRef = useRef<Waypoint[]>([]);
  const lastTargetKeyRef = useRef<string>('perch');
  const wasPanningRef = useRef<boolean>(false);
  const isBuryingRef = useRef<boolean>(false);
  const lastBuryTriggerRef = useRef<number>(burySequenceTrigger);

  // Helper to get Canvas & Root Rectangles
  const getBounds = () => {
    const rootEl = document.getElementById('swarm-widget-root');
    const canvasEl = document.getElementById('swarm-canvas-viewport');
    const rootRect = rootEl?.getBoundingClientRect() || new DOMRect(0, 0, 920, 680);
    const canvasRect = canvasEl?.getBoundingClientRect() || rootRect;
    return {
      rootRect,
      canvasRel: {
        left: canvasRect.left - rootRect.left,
        top: canvasRect.top - rootRect.top,
        right: canvasRect.right - rootRect.left - 56,
        bottom: canvasRect.bottom - rootRect.top - 56,
        width: canvasRect.width,
        height: canvasRect.height,
      },
    };
  };

  // =========================================================================
  // 1. TASK INITIATION: THE ACORN BURY SEQUENCE (Blocks Node Spawning Until Buried)
  // =========================================================================
  useEffect(() => {
    if (burySequenceTrigger <= lastBuryTriggerRef.current) return;
    lastBuryTriggerRef.current = burySequenceTrigger;
    isBuryingRef.current = true;
    waypointsRef.current = [];

    const { canvasRel } = getBounds();
    const perchX = canvasRel.right - 24;
    const perchY = 6;
    const inputOriginX = canvasRel.left + canvasRel.width * 0.45;
    const inputOriginY = canvasRel.bottom + 42;
    const digCenterX = canvasRel.left + canvasRel.width * 0.46;
    const digCenterY = canvasRel.top + canvasRel.height * 0.22;

    // Snap Byte to top-right bezel perch to catch the tossed acorn
    posRef.current = { x: perchX, y: perchY };
    setPos({ x: perchX, y: perchY });
    setAnimState('acorn_catch');

    // Step A: Arc pixelated acorn from collapsed input dock to Byte (0ms -> 520ms)
    const startTime = performance.now();
    const arcDuration = 520;

    const animateAcornArc = (now: number) => {
      const t = Math.min(1, (now - startTime) / arcDuration);
      const curX = inputOriginX + (perchX - inputOriginX) * t;
      const linearY = inputOriginY + (perchY - inputOriginY) * t;
      const arcLift = -140 * 4 * t * (1 - t);
      setAcornProjectile({ visible: true, x: curX, y: linearY + arcLift });

      if (t < 1) {
        requestAnimationFrame(animateAcornArc);
      } else {
        // Step B: Byte catches acorn and scrambles along bezel -> jumps to center canvas
        setAcornProjectile({ visible: false, x: 0, y: 0 });
        setAnimState('carry_acorn');
        waypointsRef.current = [
          { x: digCenterX, y: perchY, mode: 'bezel' }, // Run along top bezel
          { x: digCenterX, y: digCenterY, mode: 'top_down' }, // Jump into canvas & run to center
        ];
      }
    };

    requestAnimationFrame(animateAcornArc);
  }, [burySequenceTrigger]);

  // =========================================================================
  // 2. TARGET RESOLUTION & BORDER-TO-CANVAS PATHFINDING PLANNER
  // =========================================================================
  useEffect(() => {
    const interval = window.setInterval(() => {
      if (isBuryingRef.current) return;

      // Minimized Peekaboo Bar Mode: Sit directly on top of the slim progress bar
      if (isMinimized) {
        waypointsRef.current = [];
        const targetX = 148;
        const targetY = -56; // Flush on top of the 10px bar
        posRef.current = { x: targetX, y: targetY };
        setPos({ x: targetX, y: targetY });
        setAnimState(activeHitlAgentId || failedAgentId ? 'glass_knock' : 'peekaboo_snack');
        return;
      }

      // Screen-Space Panning Lock: Freeze Byte on the screen glass while user drags the canvas
      if (isCanvasPanning) {
        wasPanningRef.current = true;
        waypointsRef.current = [];
        return;
      }

      const { rootRect, canvasRel } = getBounds();
      const targetAgentId = failedAgentId || activeHitlAgentId;

      // Default Idle Perch on Top-Right Bezel
      if (!targetAgentId) {
        const perchX = canvasRel.right - 24;
        const perchY = 6;
        if (lastTargetKeyRef.current !== 'perch') {
          lastTargetKeyRef.current = 'perch';
          waypointsRef.current = [
            { x: posRef.current.x, y: perchY, mode: 'bezel' },
            { x: perchX, y: perchY, mode: 'bezel' },
          ];
        }
        return;
      }

      // Locate Target DOM Element (Node or HITL Card)
      const nodeEl =
        document.querySelector(`[data-agent-node="${targetAgentId}"]`) ||
        document.querySelector('[data-mascot-target="hitl-action-box"]');

      if (!nodeEl) return;

      const nodeRect = nodeEl.getBoundingClientRect();
      const rawX = nodeRect.left - rootRect.left + nodeRect.width * 0.5 - 32;
      const rawY = nodeRect.top - rootRect.top - 42;

      // Check if node is panned OFF-SCREEN outside the active canvas viewport
      const isOffScreen =
        rawX < canvasRel.left ||
        rawX > canvasRel.right ||
        rawY < canvasRel.top ||
        rawY > canvasRel.bottom;

      const clampedX = Math.max(canvasRel.left + 8, Math.min(canvasRel.right - 8, rawX));
      const clampedY = Math.max(canvasRel.top + 8, Math.min(canvasRel.bottom - 8, rawY));

      const targetKey = `${targetAgentId}_${Math.round(clampedX / 8)}_${Math.round(
        clampedY / 8
      )}_${isOffScreen ? 'off' : 'in'}`;

      // If user just released a canvas pan, sprint directly across the canvas to catch up
      if (wasPanningRef.current) {
        wasPanningRef.current = false;
        lastTargetKeyRef.current = targetKey;
        waypointsRef.current = [
          {
            x: clampedX,
            y: clampedY,
            mode: isOffScreen ? 'bezel' : 'top_down',
          },
        ];
        return;
      }

      // If target moved or changed, compute Border-to-Canvas path
      if (lastTargetKeyRef.current !== targetKey && waypointsRef.current.length === 0) {
        lastTargetKeyRef.current = targetKey;
        const dist = Math.hypot(clampedX - posRef.current.x, clampedY - posRef.current.y);
        if (dist < 10) return;

        // If currently on a bezel, run along the bezel first, then jump into canvas
        const isCurrentlyOnBezel = posRef.current.y <= canvasRel.top + 20;
        if (isCurrentlyOnBezel && !isOffScreen) {
          waypointsRef.current = [
            { x: clampedX, y: posRef.current.y, mode: 'bezel' }, // 1. Run horizontally along bezel
            { x: clampedX, y: clampedY, mode: 'top_down' }, // 2. Jump into canvas & run straight to node
          ];
        } else {
          waypointsRef.current = [
            { x: clampedX, y: clampedY, mode: isOffScreen ? 'bezel' : 'top_down' },
          ];
        }
      }
    }, 90);

    return () => clearInterval(interval);
  }, [isMinimized, isCanvasPanning, activeHitlAgentId, failedAgentId]);

  // =========================================================================
  // 3. CONSTANT-VELOCITY LINEAR KINEMATICS LOOP (Zero CSS Easing)
  // =========================================================================
  useEffect(() => {
    let lastTime = performance.now();
    let rafId: number;

    const stepPhysics = (now: number) => {
      const dt = Math.min(0.05, (now - lastTime) / 1000);
      lastTime = now;

      if (!isMinimized && !isCanvasPanning && waypointsRef.current.length > 0) {
        const nextWp = waypointsRef.current[0];
        const dx = nextWp.x - posRef.current.x;
        const dy = nextWp.y - posRef.current.y;
        const dist = Math.hypot(dx, dy);
        const stepDist = LINEAR_SPEED_PX_PER_SEC * dt;

        if (Math.abs(dx) > 1) {
          setFlipX(dx < 0);
        }

        if (dist <= stepDist) {
          // Instantaneous arrival at waypoint
          posRef.current = { x: nextWp.x, y: nextWp.y };
          setPos({ x: nextWp.x, y: nextWp.y });
          waypointsRef.current.shift();

          // Check if we arrived at the final waypoint
          if (waypointsRef.current.length === 0) {
            if (isBuryingRef.current) {
              // Arrived at canvas center with the acorn -> Bury it!
              setAnimState('dig');
              setDirtMoundCoord({ x: nextWp.x + 18, y: nextWp.y + 48 });

              setTimeout(() => {
                setDirtMoundCoord(null);
                isBuryingRef.current = false;
                onBuryComplete(); // Now spawn the Main Orchestrator node!
              }, 1150);
            } else if (lastTargetKeyRef.current.endsWith('_off')) {
              setAnimState('offscreen_point');
            } else if (failedAgentId) {
              setAnimState('hardhat_inspect');
            } else if (activeHitlAgentId) {
              setAnimState('wave_point');
            } else {
              setAnimState('idle');
            }
          }
        } else {
          // Strictly linear constant velocity step
          const vx = (dx / dist) * stepDist;
          const vy = (dy / dist) * stepDist;
          posRef.current = { x: posRef.current.x + vx, y: posRef.current.y + vy };
          setPos({ ...posRef.current });

          if (isBuryingRef.current) {
            setAnimState('carry_acorn');
          } else if (nextWp.mode === 'top_down') {
            setAnimState('run_canvas_topdown');
          } else if (Math.abs(dy) > Math.abs(dx)) {
            setAnimState('climb_bezel');
          } else {
            setAnimState('run_bezel');
          }
        }
      }

      rafId = requestAnimationFrame(stepPhysics);
    };

    rafId = requestAnimationFrame(stepPhysics);
    return () => cancelAnimationFrame(rafId);
  }, [isMinimized, isCanvasPanning, failedAgentId, activeHitlAgentId, onBuryComplete]);

  // Glass Knock Audio in Minimized Mode
  useEffect(() => {
    if (isMinimized && animState === 'glass_knock') {
      playGlassKnockSound();
      const id = window.setInterval(playGlassKnockSound, 2200);
      return () => clearInterval(id);
    }
  }, [isMinimized, animState]);

  const isClickable =
    (animState === 'hardhat_inspect' && failedAgentId) || isMinimized;

  return (
    <div className="pointer-events-none absolute inset-0 z-50 overflow-visible">
      {/* Tossed Pixelated Acorn Projectile */}
      {acornProjectile.visible && (
        <div
          className="absolute z-50"
          style={{
            transform: `translate3d(${acornProjectile.x}px, ${acornProjectile.y}px, 0)`,
          }}
        >
          <svg width="22" height="22" viewBox="0 0 16 16" fill="none">
            <path d="M3 6C3 3.5 5.5 2 8 2C10.5 2 13 3.5 13 6H3Z" fill="#78716c" />
            <rect x="7" y="0" width="2" height="2" fill="#a8a29e" />
            <path d="M4 6H12L10.5 13L8 15L5.5 13L4 6Z" fill="#FF6B00" />
          </svg>
        </div>
      )}

      {/* Dirt Particles when Burying Acorn at Canvas Center */}
      {dirtMoundCoord && (
        <div
          className="absolute z-40 flex items-center justify-center"
          style={{
            transform: `translate3d(${dirtMoundCoord.x}px, ${dirtMoundCoord.y}px, 0)`,
          }}
        >
          <div className="h-3 w-8 rounded-full bg-[#FF6B00]/40 blur-[2px] animate-ping" />
          <div className="absolute h-2 w-6 rounded-full border border-[#FF6B00] bg-zinc-800" />
        </div>
      )}

      {/* "Byte" Custom Sprite Sheet Container (public/sprites/byte_spritesheet.png) */}
      <div
        onClick={() => {
          if (isMinimized) {
            onExpandFromKnock();
          } else if (failedAgentId && animState === 'hardhat_inspect') {
            onInspectFailedNode(failedAgentId);
          }
        }}
        style={{
          transform: `translate3d(${Math.round(pos.x)}px, ${Math.round(pos.y)}px, 0) scaleX(${
            flipX ? -1 : 1
          })`,
        }}
        className={`byte-sprite has-custom-spritesheet ${
          isClickable ? 'pointer-events-auto cursor-pointer' : 'pointer-events-none'
        }`}
        data-state={animState}
      >
        {/* Minimalist Off-Screen Indicator Label */}
        {animState === 'offscreen_point' && (
          <div
            style={{ transform: `scaleX(${flipX ? -1 : 1})` }}
            className="absolute -top-6 left-1/2 -translate-x-1/2 whitespace-nowrap rounded border border-[#FF6B00] bg-[#0A0A0C] px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase text-[#FF6B00]"
          >
            Off-Screen Node
          </div>
        )}
      </div>
    </div>
  );
};