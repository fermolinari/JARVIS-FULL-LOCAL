// JARVIS orb — Three.js arc-reactor / atom hybrid.
import * as THREE from 'three';

const STATE_COLORS = {
    idle:      new THREE.Color(0x00b8cc),
    listening: new THREE.Color(0x00e5ff),
    thinking:  new THREE.Color(0xb388ff),
    speaking:  new THREE.Color(0x66f0ff),
    error:     new THREE.Color(0xff5252),
};

class Orb {
    constructor(canvas) {
        this.canvas = canvas;
        this.state = 'idle';
        this.targetIntensity = 0.5;
        this.intensity = 0.5;
        this.audioLevel = 0;
        this.targetColor = STATE_COLORS.idle.clone();
        this.currentColor = STATE_COLORS.idle.clone();

        this._initScene();
        this._initObjects();
        this._bindResize();
        this._tick = this._tick.bind(this);
        requestAnimationFrame(this._tick);
    }

    _initScene() {
        const w = window.innerWidth;
        const h = window.innerHeight;
        this.scene = new THREE.Scene();
        this.camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 100);
        this.camera.position.set(0, 0, 6.5);
        this.renderer = new THREE.WebGLRenderer({
            canvas: this.canvas,
            antialias: true,
            alpha: true,
        });
        this.renderer.setSize(w, h);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        this.renderer.setClearColor(0x000000, 0);
    }

    _initObjects() {
        // Inner glowing core — icosahedron with shader for organic distortion + rim lighting.
        const coreGeo = new THREE.IcosahedronGeometry(1.0, 5);
        this.coreUniforms = {
            uTime:      { value: 0 },
            uColor:     { value: this.currentColor },
            uIntensity: { value: this.intensity },
            uAudio:     { value: 0 },
        };
        const coreMat = new THREE.ShaderMaterial({
            uniforms: this.coreUniforms,
            vertexShader: `
                uniform float uTime;
                uniform float uIntensity;
                uniform float uAudio;
                varying vec3 vNormal;
                varying float vDistortion;

                // 3D simplex-ish noise (cheap)
                float hash(vec3 p) { return fract(sin(dot(p, vec3(127.1, 311.7, 74.7))) * 43758.5453); }
                float noise(vec3 p) {
                    vec3 i = floor(p), f = fract(p);
                    f = f*f*(3.0-2.0*f);
                    return mix(mix(mix(hash(i), hash(i+vec3(1,0,0)), f.x),
                                   mix(hash(i+vec3(0,1,0)), hash(i+vec3(1,1,0)), f.x), f.y),
                               mix(mix(hash(i+vec3(0,0,1)), hash(i+vec3(1,0,1)), f.x),
                                   mix(hash(i+vec3(0,1,1)), hash(i+vec3(1,1,1)), f.x), f.y), f.z);
                }

                void main() {
                    vNormal = normalize(normal);
                    float n = noise(position * 2.0 + uTime * 0.6);
                    float distort = n * 0.18 * (0.5 + uIntensity) + uAudio * 0.25;
                    vDistortion = distort;
                    vec3 newPos = position + normal * distort;
                    gl_Position = projectionMatrix * modelViewMatrix * vec4(newPos, 1.0);
                }
            `,
            fragmentShader: `
                uniform vec3 uColor;
                uniform float uIntensity;
                uniform float uTime;
                varying vec3 vNormal;
                varying float vDistortion;

                void main() {
                    // Rim lighting
                    vec3 viewDir = vec3(0.0, 0.0, 1.0);
                    float fresnel = pow(1.0 - abs(dot(vNormal, viewDir)), 2.0);
                    float pulse = 0.7 + 0.3 * sin(uTime * 2.0);
                    vec3 col = uColor * (0.6 + fresnel * 1.6) * (0.5 + uIntensity * 1.2) * pulse;
                    col += uColor * vDistortion * 2.0;
                    gl_FragColor = vec4(col, 0.92);
                }
            `,
            transparent: true,
        });
        this.core = new THREE.Mesh(coreGeo, coreMat);
        this.scene.add(this.core);

        // Glow halo — additive sphere larger than core
        const haloGeo = new THREE.IcosahedronGeometry(1.35, 3);
        this.haloUniforms = {
            uColor:     { value: this.currentColor },
            uIntensity: { value: this.intensity },
        };
        const haloMat = new THREE.ShaderMaterial({
            uniforms: this.haloUniforms,
            vertexShader: `
                varying vec3 vNormal;
                void main() {
                    vNormal = normalize(normalMatrix * normal);
                    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
                }
            `,
            fragmentShader: `
                uniform vec3 uColor;
                uniform float uIntensity;
                varying vec3 vNormal;
                void main() {
                    float fresnel = pow(1.0 - abs(dot(vNormal, vec3(0.0, 0.0, 1.0))), 3.5);
                    gl_FragColor = vec4(uColor, fresnel * 0.45 * (0.4 + uIntensity));
                }
            `,
            transparent: true,
            blending: THREE.AdditiveBlending,
            side: THREE.BackSide,
            depthWrite: false,
        });
        this.halo = new THREE.Mesh(haloGeo, haloMat);
        this.scene.add(this.halo);

        // Three concentric rings at different orientations
        this.rings = [];
        const ringSpecs = [
            { radius: 1.7, tube: 0.018, axis: new THREE.Vector3(1, 0, 0), speed: 0.4 },
            { radius: 2.0, tube: 0.012, axis: new THREE.Vector3(0, 1, 0.4).normalize(), speed: -0.6 },
            { radius: 2.3, tube: 0.008, axis: new THREE.Vector3(0.6, 0.8, 0).normalize(), speed: 0.3 },
        ];
        for (const spec of ringSpecs) {
            const geo = new THREE.TorusGeometry(spec.radius, spec.tube, 16, 128);
            const mat = new THREE.MeshBasicMaterial({
                color: this.currentColor,
                transparent: true,
                opacity: 0.85,
                blending: THREE.AdditiveBlending,
            });
            const mesh = new THREE.Mesh(geo, mat);
            mesh.userData = spec;
            // Tilt randomly
            mesh.rotation.x = Math.random() * Math.PI;
            mesh.rotation.y = Math.random() * Math.PI;
            this.scene.add(mesh);
            this.rings.push(mesh);
        }

        // Particle field — random points in a sphere
        const N = 600;
        const positions = new Float32Array(N * 3);
        for (let i = 0; i < N; i++) {
            // Random points on a thick spherical shell (radius 2.5–4)
            const r = 2.5 + Math.random() * 1.5;
            const theta = Math.random() * Math.PI * 2;
            const phi = Math.acos(2 * Math.random() - 1);
            positions[i * 3]     = r * Math.sin(phi) * Math.cos(theta);
            positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
            positions[i * 3 + 2] = r * Math.cos(phi);
        }
        const partGeo = new THREE.BufferGeometry();
        partGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        this.particleMat = new THREE.PointsMaterial({
            color: this.currentColor,
            size: 0.025,
            transparent: true,
            opacity: 0.7,
            blending: THREE.AdditiveBlending,
            depthWrite: false,
        });
        this.particles = new THREE.Points(partGeo, this.particleMat);
        this.scene.add(this.particles);
    }

    _bindResize() {
        window.addEventListener('resize', () => {
            const w = window.innerWidth;
            const h = window.innerHeight;
            this.camera.aspect = w / h;
            this.camera.updateProjectionMatrix();
            this.renderer.setSize(w, h);
        });
    }

    setState(state) {
        if (!STATE_COLORS[state]) return;
        this.state = state;
        this.targetColor = STATE_COLORS[state];
        if (state === 'idle')      this.targetIntensity = 0.4;
        if (state === 'listening') this.targetIntensity = 1.0;
        if (state === 'thinking')  this.targetIntensity = 0.85;
        if (state === 'speaking')  this.targetIntensity = 1.1;
        if (state === 'error')     this.targetIntensity = 0.7;
    }

    setAudioLevel(level) {
        this.audioLevel = Math.max(0, Math.min(1, level));
    }

    _tick(now) {
        const t = now * 0.001;

        // Smooth color transition
        this.currentColor.lerp(this.targetColor, 0.04);
        this.intensity += (this.targetIntensity - this.intensity) * 0.06;
        this.audioLevel *= 0.92;

        // Update uniforms
        this.coreUniforms.uTime.value = t;
        this.coreUniforms.uIntensity.value = this.intensity;
        this.coreUniforms.uAudio.value = this.audioLevel;
        this.haloUniforms.uIntensity.value = this.intensity + this.audioLevel * 0.5;
        this.particleMat.color.copy(this.currentColor);
        this.particleMat.size = 0.022 + this.intensity * 0.012;

        // Rotate rings (faster when thinking/listening)
        const stateMul = this.state === 'thinking' ? 3.0 :
                         this.state === 'listening' ? 1.6 :
                         this.state === 'speaking' ? 1.2 : 1.0;
        for (const ring of this.rings) {
            const spec = ring.userData;
            ring.rotateOnAxis(spec.axis, spec.speed * 0.012 * stateMul);
            ring.material.color.copy(this.currentColor);
            ring.material.opacity = 0.55 + this.intensity * 0.4;
        }

        // Slowly rotate particles
        this.particles.rotation.y = t * 0.05;
        this.particles.rotation.x = t * 0.03;

        // Core slow rotation
        this.core.rotation.y = t * 0.2;
        this.core.rotation.x = t * 0.13;
        this.halo.rotation.y = -t * 0.08;

        this.renderer.render(this.scene, this.camera);
        requestAnimationFrame(this._tick);
    }
}

const canvas = document.getElementById('orb-canvas');
window.orb = new Orb(canvas);
