// JARVIS orb — casulo dourado de filamentos estilo Iron Man (Extremis / Mark cradle).
// Núcleo emissivo + dezenas de tubos curvos formando uma esfera caótica de fios.
import * as THREE from 'three';

const STATE_COLORS = {
    idle:      new THREE.Color(0xff8800),  // âmbar
    listening: new THREE.Color(0xffb74d),  // dourado claro
    thinking:  new THREE.Color(0xff5722),  // vermelho-laranja quente
    speaking:  new THREE.Color(0xffd180),  // amarelo-ouro brilhante
    error:     new THREE.Color(0xff1744),  // vermelho profundo
};

const HOT_CORE = new THREE.Color(0xfff3c4);  // miolo branco-quente

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
        this.camera.position.set(0, 0, 7.0);
        this.renderer = new THREE.WebGLRenderer({
            canvas: this.canvas,
            antialias: true,
            alpha: true,
        });
        this.renderer.setSize(w, h);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        this.renderer.setClearColor(0x000000, 0);

        // Container que rotaciona o casulo inteiro (filamentos + halo)
        this.cocoon = new THREE.Group();
        this.scene.add(this.cocoon);
    }

    _initObjects() {
        this._buildCore();
        this._buildFilaments();
        this._buildHalo();
        this._buildParticles();
    }

    _buildCore() {
        // Núcleo — pequeno e branco-quente, com pulso e fresnel
        const geo = new THREE.IcosahedronGeometry(0.55, 5);
        this.coreUniforms = {
            uTime:      { value: 0 },
            uColor:     { value: this.currentColor },
            uHot:       { value: HOT_CORE },
            uIntensity: { value: this.intensity },
            uAudio:     { value: 0 },
        };
        const mat = new THREE.ShaderMaterial({
            uniforms: this.coreUniforms,
            vertexShader: `
                uniform float uTime;
                uniform float uIntensity;
                uniform float uAudio;
                varying vec3 vNormal;
                varying float vDist;

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
                    float n = noise(position * 3.0 + uTime * 0.8);
                    float d = n * 0.10 * (0.4 + uIntensity) + uAudio * 0.18;
                    vDist = d;
                    vec3 p = position + normal * d;
                    gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
                }
            `,
            fragmentShader: `
                uniform vec3 uColor;
                uniform vec3 uHot;
                uniform float uIntensity;
                uniform float uTime;
                varying vec3 vNormal;
                varying float vDist;
                void main() {
                    float fres = pow(1.0 - abs(dot(vNormal, vec3(0.0, 0.0, 1.0))), 1.6);
                    float pulse = 0.75 + 0.25 * sin(uTime * 2.4);
                    // Mistura branco-quente no centro com tom do estado nas bordas
                    vec3 col = mix(uHot, uColor, fres);
                    col *= (0.7 + uIntensity * 1.4) * pulse;
                    col += uColor * vDist * 3.0;
                    gl_FragColor = vec4(col, 0.95);
                }
            `,
            transparent: true,
        });
        this.core = new THREE.Mesh(geo, mat);
        this.scene.add(this.core);
    }

    _buildFilaments() {
        // Gera N curvas aleatórias passando perto da superfície de uma esfera,
        // cada uma com 6-10 pontos de controle. Renderiza como TubeGeometry.
        const NUM_FILAMENTS = 42;
        const tubeMat = new THREE.MeshBasicMaterial({
            color: this.currentColor,
            transparent: true,
            opacity: 0.85,
            blending: THREE.AdditiveBlending,
            depthWrite: false,
        });
        // Compartilhamos um material só pra economizar — clones só se precisar variar opacidade
        this.filamentMat = tubeMat;
        this.filaments = [];

        const rand = (a, b) => a + Math.random() * (b - a);

        for (let i = 0; i < NUM_FILAMENTS; i++) {
            const numPts = 6 + Math.floor(Math.random() * 5);
            const pts = [];
            // Cada filamento orbita em torno de um eixo aleatório, com raios variando
            const baseRadius = rand(1.4, 2.4);
            const axis = new THREE.Vector3(
                rand(-1, 1), rand(-1, 1), rand(-1, 1)
            ).normalize();
            const tangent = new THREE.Vector3(
                rand(-1, 1), rand(-1, 1), rand(-1, 1)
            ).normalize();
            // Garante perpendicularidade aproximada
            tangent.crossVectors(axis, tangent).normalize();

            const startAngle = Math.random() * Math.PI * 2;
            const arcLen = rand(Math.PI * 0.8, Math.PI * 2.4);
            for (let j = 0; j < numPts; j++) {
                const t = j / (numPts - 1);
                const ang = startAngle + arcLen * t;
                // Raio com pequena variação para parecer "amassado"
                const r = baseRadius * (0.85 + 0.3 * Math.sin(ang * 1.7 + i));
                // Vetor sobre o plano (axis, tangent), girado por 'ang'
                const v = new THREE.Vector3()
                    .copy(tangent).multiplyScalar(Math.cos(ang) * r)
                    .add(new THREE.Vector3().crossVectors(axis, tangent).multiplyScalar(Math.sin(ang) * r))
                    .add(axis.clone().multiplyScalar(rand(-0.6, 0.6) * baseRadius));
                pts.push(v);
            }
            const curve = new THREE.CatmullRomCurve3(pts, false, 'catmullrom', 0.4);
            const tubeGeo = new THREE.TubeGeometry(curve, 64, rand(0.008, 0.022), 6, false);
            const mesh = new THREE.Mesh(tubeGeo, tubeMat.clone());
            mesh.userData = {
                spinAxis: axis.clone(),
                spinSpeed: rand(-0.18, 0.18),
                phase: Math.random() * Math.PI * 2,
                bobAmp: rand(0.0, 0.04),
            };
            this.cocoon.add(mesh);
            this.filaments.push(mesh);
        }
    }

    _buildHalo() {
        const geo = new THREE.IcosahedronGeometry(2.6, 3);
        this.haloUniforms = {
            uColor:     { value: this.currentColor },
            uIntensity: { value: this.intensity },
        };
        const mat = new THREE.ShaderMaterial({
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
                    float fres = pow(1.0 - abs(dot(vNormal, vec3(0.0, 0.0, 1.0))), 3.5);
                    gl_FragColor = vec4(uColor, fres * 0.35 * (0.4 + uIntensity));
                }
            `,
            transparent: true,
            blending: THREE.AdditiveBlending,
            side: THREE.BackSide,
            depthWrite: false,
        });
        this.halo = new THREE.Mesh(geo, mat);
        this.scene.add(this.halo);
    }

    _buildParticles() {
        const N = 350;
        const positions = new Float32Array(N * 3);
        for (let i = 0; i < N; i++) {
            const r = 2.7 + Math.random() * 1.6;
            const theta = Math.random() * Math.PI * 2;
            const phi = Math.acos(2 * Math.random() - 1);
            positions[i * 3]     = r * Math.sin(phi) * Math.cos(theta);
            positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
            positions[i * 3 + 2] = r * Math.cos(phi);
        }
        const geo = new THREE.BufferGeometry();
        geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        this.particleMat = new THREE.PointsMaterial({
            color: this.currentColor,
            size: 0.030,
            transparent: true,
            opacity: 0.7,
            blending: THREE.AdditiveBlending,
            depthWrite: false,
        });
        this.particles = new THREE.Points(geo, this.particleMat);
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
        if (state === 'idle')      this.targetIntensity = 0.45;
        if (state === 'listening') this.targetIntensity = 1.0;
        if (state === 'thinking')  this.targetIntensity = 0.85;
        if (state === 'speaking')  this.targetIntensity = 1.15;
        if (state === 'error')     this.targetIntensity = 0.7;
    }

    setAudioLevel(level) {
        this.audioLevel = Math.max(0, Math.min(1, level));
    }

    _tick(now) {
        const t = now * 0.001;

        // Suavização
        this.currentColor.lerp(this.targetColor, 0.04);
        this.intensity += (this.targetIntensity - this.intensity) * 0.06;
        this.audioLevel *= 0.92;

        // Núcleo
        this.coreUniforms.uTime.value = t;
        this.coreUniforms.uIntensity.value = this.intensity;
        this.coreUniforms.uAudio.value = this.audioLevel;
        // Cor do núcleo segue currentColor pra estados (mas mistura HOT_CORE no shader)
        this.coreUniforms.uColor.value.copy(this.currentColor);

        // Halo
        this.haloUniforms.uIntensity.value = this.intensity + this.audioLevel * 0.5;
        this.haloUniforms.uColor.value.copy(this.currentColor);

        // Casulo de filamentos — rotação global lenta
        const stateMul = this.state === 'thinking' ? 2.2 :
                         this.state === 'listening' ? 1.4 :
                         this.state === 'speaking' ? 1.6 : 1.0;
        this.cocoon.rotation.y += 0.0015 * stateMul;
        this.cocoon.rotation.x += 0.0008 * stateMul;

        // Cada filamento "respira" individualmente + rotação local
        const opacBase = 0.55 + this.intensity * 0.4 + this.audioLevel * 0.25;
        for (const f of this.filaments) {
            const u = f.userData;
            f.rotateOnAxis(u.spinAxis, u.spinSpeed * 0.006 * stateMul);
            const bob = 1.0 + u.bobAmp * Math.sin(t * 1.7 + u.phase) * (0.6 + this.intensity);
            f.scale.setScalar(bob);
            f.material.color.copy(this.currentColor);
            f.material.opacity = Math.min(1.0, opacBase + Math.sin(t * 2.0 + u.phase) * 0.08);
        }

        // Partículas
        this.particleMat.color.copy(this.currentColor);
        this.particleMat.size = 0.026 + this.intensity * 0.014;
        this.particles.rotation.y = t * 0.05;
        this.particles.rotation.x = t * 0.03;

        // Núcleo gira de leve
        this.core.rotation.y = t * 0.25;
        this.core.rotation.x = t * 0.17;
        this.halo.rotation.y = -t * 0.08;

        this.renderer.render(this.scene, this.camera);
        requestAnimationFrame(this._tick);
    }
}

const canvas = document.getElementById('orb-canvas');
window.orb = new Orb(canvas);
