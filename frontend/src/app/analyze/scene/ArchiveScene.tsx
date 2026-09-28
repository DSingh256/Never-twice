"use client";

/* The Black Box Archive scene.
 *
 * Every visual quantity is a pure function of one shared scalar `p` (0..1)
 * that the scroll layer writes (gsap timeline scrub or a reduced-motion
 * fallback). No autoplay; scrolling forward and backward scrubs the whole
 * sequence.
 */

import { useEffect, useMemo, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import * as THREE from "three";

export type MemoryNode = {
  id: string;
  text: string;
  score: number;
  tags: string[];
  slot: number;
};

export type SceneLink = { nodeSlot: number; strength: number };

/* deterministic pseudo-random from a string id — stable node layouts */
function seeded(str: string) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return () => {
    h += 0x6d2b79f5;
    let t = h;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const NIGHT = new THREE.Color("#0b0908");
const AMBER = new THREE.Color("#f59e0b");
const VELLUM = new THREE.Color("#ece4d4");
const ORIGIN = new THREE.Vector3(0, 0, 0);

/* ------------------------------------------------------------------ */
/* Black box: matte dark body, bevelled lid, engraved plates, beacons  */
/* ------------------------------------------------------------------ */
function BlackBox({ p }: { p: React.RefObject<number> }) {
  const group = useRef<THREE.Group>(null);
  const beacon = useRef<THREE.Mesh>(null);
  const beacon2 = useRef<THREE.Mesh>(null);

  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    const v = p.current ?? 0;
    const g = group.current;
    if (!g) return;
    // scroll drives rotation + heading; a whisper of idle breath on top
    g.rotation.y = (v * Math.PI) / 2.1 + Math.sin(t * 0.22) * 0.05;
    g.rotation.x = Math.sin(v * Math.PI) * 0.08 + Math.sin(t * 0.31) * 0.02;
    g.position.y = Math.sin(t * 0.5) * 0.05 - v * 0.3;
    const pulse = 1.6 + Math.sin(t * (1.2 + v * 2.4)) * 0.5;
    const m1 = beacon.current?.material as THREE.MeshStandardMaterial;
    const m2 = beacon2.current?.material as THREE.MeshStandardMaterial;
    if (m1) m1.emissiveIntensity = pulse;
    if (m2) m2.emissiveIntensity = 2.2 - pulse * 0.3;
  });

  const metal = (
    <meshStandardMaterial color="#181512" roughness={0.42} metalness={0.85} />
  );
  const plateMat = (
    <meshStandardMaterial color="#232019" roughness={0.55} metalness={0.6} />
  );

  return (
    <group ref={group}>
      {/* main body */}
      <mesh castShadow>
        <boxGeometry args={[2.1, 1.2, 1.3]} />
        {metal}
      </mesh>
      {/* lid with bevel */}
      <mesh position={[0, 0.64, 0]} castShadow>
        <boxGeometry args={[2.16, 0.14, 1.36]} />
        <meshStandardMaterial color="#1e1a16" roughness={0.35} metalness={0.9} />
      </mesh>
      {/* forensically numbered face plate */}
      <mesh position={[0, 0.1, 0.656]}>
        <planeGeometry args={[1.5, 0.6]} />
        {plateMat}
      </mesh>
      {/* data ports */}
      {[-0.6, 0, 0.6].map((x) => (
        <mesh key={x} position={[x, -0.35, 0.656]}>
          <planeGeometry args={[0.3, 0.12]} />
          <meshStandardMaterial color="#0c0a08" roughness={0.9} />
        </mesh>
      ))}
      {/* signal beacons */}
      <mesh ref={beacon} position={[0.72, 0.74, 0.42]}>
        <cylinderGeometry args={[0.045, 0.045, 0.05, 16]} />
        <meshStandardMaterial
          color="#f59e0b"
          emissive="#f59e0b"
          emissiveIntensity={2}
        />
      </mesh>
      <mesh ref={beacon2} position={[0.72, 0.74, 0.56]}>
        <cylinderGeometry args={[0.045, 0.045, 0.05, 16]} />
        <meshStandardMaterial
          color="#f59e0b"
          emissive="#f59e0b"
          emissiveIntensity={1.4}
        />
      </mesh>
      {/* inner memory core, faintly visible through the lattice ends */}
      <mesh position={[0, 0, 0]}>
        <boxGeometry args={[1.5, 0.7, 0.9]} />
        <meshStandardMaterial
          color="#2a2013"
          emissive="#f59e0b"
          emissiveIntensity={0.22}
          roughness={0.9}
        />
      </mesh>
    </group>
  );
}

/* ------------------------------------------------------------------ */
/* Memory constellation: real recall hits, deterministic orbital slots */
/* ------------------------------------------------------------------ */
function Constellation({
  nodes,
  links,
  p,
}: {
  nodes: MemoryNode[];
  links: SceneLink[];
  p: React.RefObject<number>;
}) {
  const group = useRef<THREE.Group>(null);
  const linkMeshes = useRef<THREE.Line[]>([]);

  const placements = useMemo(() => {
    return nodes.map((n, i) => {
      const rnd = seeded(n.id);
      const ring = 2.6 + rnd() * 3.2;
      const theta = (i / Math.max(nodes.length, 1)) * Math.PI * 2 + rnd() * 0.8;
      const y = (rnd() - 0.5) * 3.4;
      return new THREE.Vector3(
        Math.cos(theta) * ring,
        y,
        Math.sin(theta) * ring
      );
    });
  }, [nodes]);

  const linkSet = useMemo(() => new Set(links.map((l) => l.nodeSlot)), [links]);

  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    const v = p.current ?? 0;
    const g = group.current;
    if (!g) return;
    g.rotation.y = 0.4 + v * Math.PI * 1.15 + t * 0.02;
    // constellation fades out again toward the verdict
    const appear = THREE.MathUtils.smoothstep(v, 0.18, 0.42);
    const retreat = 1 - THREE.MathUtils.smoothstep(v, 0.78, 0.96);
    const s = appear * retreat;
    g.scale.setScalar(0.001 + s * (0.75 + v * 0.45));
    g.visible = s > 0.01;

    linkMeshes.current.forEach((line) => {
      const mat = line.material as THREE.LineBasicMaterial;
      mat.opacity = THREE.MathUtils.clamp(
        mat.userData.baseOpacity * (0.2 + v * 0.9) * retreat,
        0,
        0.85
      );
    });
  });

  return (
    <group ref={group}>
      {nodes.map((n, i) => (
        <MemorySphere
          key={n.id}
          position={placements[i]}
          strength={linkSet.has(i) ? 1 : 0.25}
          strong={linkSet.has(i)}
        />
      ))}
      {links.map((l, li) => (
        <PrimitiveLine
          key={li}
          ref={(mesh) => {
            if (mesh) linkMeshes.current[li] = mesh as unknown as THREE.Line;
          }}
          to={placements[l.nodeSlot]}
          opacity={0.18 + l.strength * 0.5}
        />
      ))}
    </group>
  );
}

function MemorySphere({
  position,
  strength,
  strong,
}: {
  position: THREE.Vector3;
  strength: number;
  strong: boolean;
}) {
  const ref = useRef<THREE.Mesh>(null);
  useFrame(({ clock }) => {
    const m = ref.current?.material as THREE.MeshStandardMaterial;
    if (m)
      m.emissiveIntensity =
        (strong ? 1.15 : 0.3) + Math.sin(clock.elapsedTime * 0.9 + position.x) * 0.12;
  });
  return (
    <mesh ref={ref} position={position}>
      <icosahedronGeometry args={[strong ? 0.11 : 0.075, 1]} />
      <meshStandardMaterial
        color={strong ? AMBER : VELLUM}
        emissive={strong ? AMBER : VELLUM}
        emissiveIntensity={0.4}
        roughness={0.5}
        transparent
        opacity={Math.min(1, 0.35 + strength)}
      />
    </mesh>
  );
}

function PrimitiveLine({
  to,
  opacity,
  ref,
}: {
  to: THREE.Vector3;
  opacity: number;
  ref?: React.Ref<THREE.Line>;
}) {
  // Geometry + material are created once per (target, opacity); disposed on
  // unmount so node-set changes never leak GPU resources.
  const line = useMemo(() => {
    const geometry = new THREE.BufferGeometry().setFromPoints([ORIGIN, to]);
    const material = new THREE.LineBasicMaterial({
      color: AMBER,
      transparent: true,
      opacity,
    });
    material.userData = { baseOpacity: opacity };
    return new THREE.Line(geometry, material);
  }, [to, opacity]);

  useEffect(() => {
    return () => {
      line.geometry.dispose();
      (line.material as THREE.Material).dispose();
    };
  }, [line]);

  return <primitive ref={ref} object={line} />;
}

/* ------------------------------------------------------------------ */
/* Drifting archival particles (count scales with device tier)         */
/* ------------------------------------------------------------------ */
function Particles({ count, p }: { count: number; p: React.RefObject<number> }) {
  const ref = useRef<THREE.Points>(null);
  const positions = useMemo(() => {
    const arr = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      const r = 3.5 + Math.random() * 6;
      const th = Math.random() * Math.PI * 2;
      arr[i * 3] = Math.cos(th) * r;
      arr[i * 3 + 1] = (Math.random() - 0.5) * 7;
      arr[i * 3 + 2] = Math.sin(th) * r;
    }
    return arr;
  }, [count]);

  useFrame(({ clock }) => {
    const pts = ref.current;
    if (!pts) return;
    const v = p.current ?? 0;
    pts.rotation.y = clock.elapsedTime * 0.014 + v * 0.5;
    const mat = pts.material as THREE.PointsMaterial;
    // converge inward as the archive opens, thin out at the verdict
    const converge = 1 - 0.45 * THREE.MathUtils.smoothstep(v, 0.15, 0.5);
    const fade = 1 - THREE.MathUtils.smoothstep(v, 0.85, 1);
    mat.opacity = 0.5 * fade;
    pts.scale.setScalar(converge);
  });

  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
      </bufferGeometry>
      <pointsMaterial
        size={0.035}
        color="#d8cfbc"
        transparent
        opacity={0.5}
        sizeAttenuation
        depthWrite={false}
      />
    </points>
  );
}

/* ------------------------------------------------------------------ */
/* Camera rig: scroll = the cinematographer                            */
/* ------------------------------------------------------------------ */
function CameraRig({ p }: { p: React.RefObject<number> }) {
  const tmp = useMemo(() => new THREE.Vector3(), []);
  useFrame(({ camera }) => {
    const v = p.current ?? 0;
    // three shots: push-in, orbit, pull-back
    const push = THREE.MathUtils.smoothstep(v, 0, 0.3);
    const orbit = THREE.MathUtils.smoothstep(v, 0.3, 0.75);
    const exit = THREE.MathUtils.smoothstep(v, 0.75, 1);
    const radius = THREE.MathUtils.lerp(8.2, 5.4, push) - orbit * 1.1 + exit * 4.2;
    const angle = 0.35 + orbit * Math.PI * 0.75 + exit * 0.4;
    const height = 1.6 + push * 0.9 - orbit * 0.35 + exit * 1.4;
    tmp.set(
      Math.sin(angle) * radius,
      height,
      Math.cos(angle) * radius
    );
    camera.position.lerp(tmp, 0.08);
    camera.lookAt(0, -v * 0.2, 0);
  });
  return null;
}

/* ------------------------------------------------------------------ */
/* Scene root                                                          */
/* ------------------------------------------------------------------ */
export default function ArchiveScene({
  progressRef,
  nodes,
  links,
  quality = "high",
  interactive = true,
}: {
  progressRef: React.RefObject<number>;
  nodes: MemoryNode[];
  links: SceneLink[];
  quality?: "high" | "medium" | "low";
  interactive?: boolean;
}) {
  const particleCount = quality === "high" ? 420 : quality === "medium" ? 180 : 70;
  const dpr: [number, number] =
    quality === "high" ? [1, 2] : quality === "medium" ? [1, 1.5] : [0.75, 1];

  return (
    <Canvas
      className={interactive ? "cursor-grab active:cursor-grabbing" : ""}
      dpr={dpr}
      camera={{ position: [2.5, 2.2, 8], fov: 42 }}
      gl={{ antialias: quality === "high", alpha: true, powerPreference: "high-performance" }}
      onCreated={({ gl, scene }) => {
        scene.background = NIGHT;
        scene.fog = new THREE.Fog(NIGHT, 9, 22);
        gl.toneMapping = THREE.ACESFilmicToneMapping;
      }}
    >
      <ambientLight intensity={0.16} />
      <spotLight
        position={[6, 7, 4]}
        angle={0.45}
        penumbra={0.9}
        intensity={90}
        color="#ffd9a0"
        castShadow={quality === "high"}
      />
      <pointLight position={[-5, 2, -4]} intensity={26} color="#f59e0b" />
      <pointLight position={[0, -3, 5]} intensity={9} color="#4a4038" />

      <BlackBox p={progressRef} />
      <Constellation nodes={nodes} links={links} p={progressRef} />
      <Particles count={particleCount} p={progressRef} />
      <CameraRig p={progressRef} />
    </Canvas>
  );
}
