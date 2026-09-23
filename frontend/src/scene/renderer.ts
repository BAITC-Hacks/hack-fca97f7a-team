import * as THREE from 'three'
import type { Site } from '../types'
import type { NormalizedWeatherState, SceneQuality } from '../experience/types'
import { clamp, smoothstep, WeatherInterpolator } from '../experience/weather'
import { createEarth, createSky, createWeatherEffects, skyLighting } from './environment'
import { DEG, earthPoint, EARTH_RADIUS, ScalarSpring, sphericalDirection, surfaceFrame } from './geography'
import { createTerrain, createTurbine } from './turbine'
import type { TurbineModel } from './turbine'

export interface SceneState {
  sites: Site[]
  selectedSite: Site | null
  view: 'earth' | 'turbine'
  weather: NormalizedWeatherState | null
  quality?: SceneQuality
  reducedMotion?: boolean
}
export interface MarkerProjection { id: string; x: number; y: number; visible: boolean; anchorX: number; anchorY: number }
interface SceneCallbacks {
  markers: (markers: MarkerProjection[]) => void
  quality: (quality: string) => void
  fail: () => void
  ready: () => void
}

function disposeObject(root: THREE.Object3D) {
  const geometries = new Set<THREE.BufferGeometry>(), materials = new Set<THREE.Material>(), textures = new Set<THREE.Texture>()
  root.traverse(object => {
    const mesh = object as THREE.Mesh
    if (mesh.geometry) geometries.add(mesh.geometry)
    if (mesh.material) for (const material of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) materials.add(material)
  })
  for (const material of materials) {
    for (const value of Object.values(material)) if (value instanceof THREE.Texture) textures.add(value)
    if (material instanceof THREE.ShaderMaterial) for (const { value } of Object.values(material.uniforms)) if (value instanceof THREE.Texture) textures.add(value)
    material.dispose()
  }
  for (const geometry of geometries) geometry.dispose()
  for (const texture of textures) texture.dispose()
}

/** One geocentric scene from orbit to the surface. React only changes targets. */
export class WorldRenderer {
  private renderer: THREE.WebGLRenderer
  private scene = new THREE.Scene()
  private camera = new THREE.PerspectiveCamera(42, 1, 0.0006, 100000)
  private earth = createEarth()
  private sky = createSky()
  private weatherEffects = createWeatherEffects()
  private weather = new WeatherInterpolator()
  private sun = new THREE.DirectionalLight('#fff0d9', 3)
  private fill = new THREE.HemisphereLight('#afc8db', '#625e4b', 1.5)
  private nightFill = new THREE.DirectionalLight('#86a7d3', 0)
  private local = new THREE.Group()
  private localBase: Site | null = null
  private models: { site: Site; model: TurbineModel }[] = []
  private localFrame = surfaceFrame({ latitude: 43.64515, longitude: 78.535604 })
  private state: SceneState = { sites: [], selectedSite: null, view: 'earth', weather: null }
  private flight = new ScalarSpring(0, 0, 2.5)
  private zoom = new ScalarSpring(3.52, 3.3, 2.4)
  private orbitLatitude = 24 * DEG
  private orbitLongitude = 44 * DEG
  private orbitVelocity = new THREE.Vector2()
  private flightStartNormal = earthPoint(24, 44, 1)
  private flightStartAltitude = EARTH_RADIUS * 2.3
  private localAzimuth = new ScalarSpring(3.48, 3.48, 8)
  private localElevation = new ScalarSpring(-0.012, -0.012, 8)
  private localDistance = new ScalarSpring(0.23, 0.23, 8)
  private width = 1
  private height = 1
  private raf = 0
  private lastTime = 0
  private disposed = false
  private active = true
  private ready = false
  private pointer: { id: number; x: number; y: number; at: number; moved: boolean } | null = null
  private points = new Map<number, THREE.Vector2>()
  private pinchDistance = 0
  private resizeObserver: ResizeObserver
  private actualQuality: 'low' | 'medium' | 'high' = 'high'
  private frameSum = 0
  private frameCount = 0
  private qualityAt = 0
  private targetWorld = new THREE.Vector3()
  private selectedFrame = this.localFrame
  private anchorLatitude = new ScalarSpring(43.64515, 43.64515, 4.6)
  private anchorLongitude = new ScalarSpring(78.535604, 78.535604, 4.6)
  private projection = new THREE.Vector3()
  private temp = new THREE.Vector3()
  private temp2 = new THREE.Vector3()
  private emptyMarkers: MarkerProjection[] = []
  private hasInteracted = false
  private textureResolution = 0
  private requestedTextureResolution = 0
  private textureRequest = 0
  private terrain: ReturnType<typeof createTerrain> | null = null

  constructor(private container: HTMLElement, private callbacks: SceneCallbacks) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance', logarithmicDepthBuffer: true })
    this.renderer.outputColorSpace = THREE.SRGBColorSpace
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping
    this.renderer.toneMappingExposure = 1.1
    this.renderer.setClearColor('#071016')
    this.renderer.shadowMap.type = THREE.PCFShadowMap
    this.renderer.domElement.setAttribute('aria-hidden', 'true')
    this.renderer.domElement.className = 'world-canvas'
    container.prepend(this.renderer.domElement)
    this.scene.add(this.earth.mesh, this.earth.atmosphere, this.sky.mesh, this.local, this.sun, this.sun.target, this.fill, this.nightFill, this.nightFill.target)
    this.sun.castShadow = true
    this.sun.shadow.camera.near = 0.001
    this.sun.shadow.camera.far = 3
    this.sun.shadow.camera.left = -0.23; this.sun.shadow.camera.right = 0.23
    this.sun.shadow.camera.top = 0.23; this.sun.shadow.camera.bottom = -0.23
    this.sun.shadow.bias = -0.00004
    this.sun.shadow.normalBias = 0.00015
    this.sun.shadow.mapSize.setScalar(1024)
    this.setQuality('auto')
    this.resizeObserver = new ResizeObserver(() => this.resize())
    this.resizeObserver.observe(container)
    this.resize()
    const canvas = this.renderer.domElement
    canvas.addEventListener('pointerdown', this.pointerDown)
    canvas.addEventListener('pointermove', this.pointerMove)
    canvas.addEventListener('pointerup', this.pointerUp)
    canvas.addEventListener('pointercancel', this.pointerUp)
    canvas.addEventListener('wheel', this.wheel, { passive: false })
    canvas.addEventListener('webglcontextlost', this.contextLost)
    document.addEventListener('visibilitychange', this.visibility)
    document.addEventListener('pointerdown', this.stopAmbientMotion, true)
    document.addEventListener('keydown', this.stopAmbientMotion, true)
    this.loadEarthTexture(2048)
    this.raf = requestAnimationFrame(this.frame)
  }

  update(state: SceneState) {
    const old = this.state
    this.state = state
    if (state.view === 'turbine' || state.reducedMotion) this.stopAmbientMotion()
    if (state.quality !== old.quality) this.setQuality(state.quality ?? 'auto')
    if (state.weather !== old.weather) this.weather.setTarget(state.weather)
    if (state.selectedSite && (state.selectedSite.turbine_id !== old.selectedSite?.turbine_id || this.models.length === 0)) {
      if (state.selectedSite.turbine_id !== old.selectedSite?.turbine_id) {
        // Inertia belongs to one turbine; never carry another site's wind into a loading state.
        this.weather.currentVisualState.rotorSpeed = 0
        this.weather.currentVisualState.windSpeed = 0
      }
      this.selectedFrame = surfaceFrame(state.selectedSite)
      this.anchorLatitude.target = state.selectedSite.latitude
      this.anchorLongitude.target = this.anchorLongitude.value + Math.atan2(
        Math.sin((state.selectedSite.longitude - this.anchorLongitude.value) * DEG),
        Math.cos((state.selectedSite.longitude - this.anchorLongitude.value) * DEG),
      ) / DEG
      if (this.flight.value < 0.005 || state.reducedMotion) {
        this.anchorLatitude.value = this.anchorLatitude.target
        this.anchorLongitude.value = this.anchorLongitude.target
        this.anchorLatitude.velocity = this.anchorLongitude.velocity = 0
      }
      if (state.view === 'turbine') {
        if (!this.localBase || this.localFrame.origin.distanceTo(this.selectedFrame.origin) > 25) this.buildLocal(state.selectedSite)
        else if (old.sites !== state.sites) this.buildLocal(this.localBase)
      }
    }
    const target = state.view === 'turbine' && state.selectedSite ? 1 : 0
    if (target === 1 && this.flight.target === 0 && this.flight.value < 0.005) {
      this.flightStartNormal.copy(earthPoint(this.orbitLatitude / DEG, this.orbitLongitude / DEG, 1))
      this.flightStartAltitude = Math.max(1, this.camera.position.length() - EARTH_RADIUS)
    }
    this.flight.target = target
    if (state.reducedMotion) { this.flight.value = target; this.flight.velocity = 0; this.orbitVelocity.set(0, 0) }
  }

  private buildLocal(site: Site) {
    this.local.remove(this.weatherEffects.group)
    disposeObject(this.local)
    this.local.clear()
    this.localBase = site
    this.localFrame = surfaceFrame(site)
    this.local.position.copy(this.localFrame.origin)
    this.local.quaternion.copy(this.localFrame.quaternion)
    const inverse = this.localFrame.quaternion.clone().invert()
    const nearby = this.state.sites.filter(item => earthPoint(item.latitude, item.longitude).distanceTo(this.localFrame.origin) < 20)
    if (!nearby.length) nearby.push(site)
    this.models = nearby.map(item => {
      const model = createTurbine(item.turbine_id)
      model.group.position.copy(earthPoint(item.latitude, item.longitude).sub(this.localFrame.origin).applyQuaternion(inverse))
      this.local.add(model.group)
      return { site: item, model }
    })
    this.terrain = createTerrain(this.models.map(item => item.model.group.position))
    this.local.add(this.terrain.group, this.weatherEffects.group)
  }

  private setQuality(quality: SceneQuality) {
    const lowMemory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory
    this.actualQuality = quality === 'auto'
      ? (lowMemory != null && lowMemory <= 4) || navigator.hardwareConcurrency <= 4 ? 'medium' : 'high'
      : quality
    const cap = this.actualQuality === 'high' ? 2 : this.actualQuality === 'medium' ? 1.25 : 1
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, cap))
    this.sun.shadow.mapSize.setScalar(this.actualQuality === 'high' ? 1024 : 512)
    this.sun.shadow.map?.dispose(); this.sun.shadow.map = null
    this.callbacks.quality(this.actualQuality)
    if (this.textureResolution) this.upgradeEarthTexture()
  }

  private resize() {
    this.width = Math.max(1, this.container.clientWidth)
    this.height = Math.max(1, this.container.clientHeight)
    this.renderer.setSize(this.width, this.height, false)
    this.camera.aspect = this.width / this.height
    this.camera.updateProjectionMatrix()
    if (this.textureResolution) this.upgradeEarthTexture()
  }

  private upgradeEarthTexture() {
    const memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory
    const maxSize = this.renderer.capabilities.maxTextureSize
    // A single 8K colour map incl. mipmaps is capped at ~171 MiB. Mobile / memory-
    // limited devices receive 4K (~43 MiB), Low receives 2K (~11 MiB).
    const canUse8k = this.width >= 1000 && (memory == null || memory >= 8)
      && navigator.hardwareConcurrency > 4 && maxSize >= 8192
    const preferred = this.state.quality ?? 'auto'
    const size = this.actualQuality === 'low' || maxSize < 4096 ? 2048
      : preferred === 'medium' || !canUse8k ? 4096 : 8192
    if (size === this.textureResolution && this.requestedTextureResolution !== size) {
      ++this.textureRequest // Cancel a higher tier that is still loading after a quality reduction.
      this.requestedTextureResolution = size
      return
    }
    if (size !== this.textureResolution && size !== this.requestedTextureResolution) this.loadEarthTexture(size)
  }

  private loadEarthTexture(resolution: number) {
    const request = ++this.textureRequest
    this.requestedTextureResolution = resolution
    const path = resolution === 2048 ? '/scene/earth-blue-marble.jpg' : `/scene/earth-blue-marble-${resolution === 8192 ? '8k' : '4k'}.webp`
    new THREE.TextureLoader().load(path, texture => {
      if (this.disposed || request !== this.textureRequest) { texture.dispose(); return }
      texture.colorSpace = THREE.SRGBColorSpace
      texture.anisotropy = Math.min(16, this.renderer.capabilities.getMaxAnisotropy())
      const previous = this.earth.uniforms.surface.value
      this.earth.uniforms.surface.value = texture
      this.earth.uniforms.textured.value = 1
      this.textureResolution = resolution
      this.container.dataset.earthTexture = String(resolution)
      previous?.dispose()
      if (resolution === 2048) this.upgradeEarthTexture()
    }, undefined, () => { /* Keep the last complete local texture if a higher tier is unavailable. */ })
  }

  private stopAmbientMotion = () => {
    if (this.hasInteracted) return
    this.hasInteracted = true
    this.zoom.target = this.zoom.value
    this.zoom.velocity = 0
    this.zoom.frequency = 8
    this.orbitVelocity.set(0, 0)
  }

  zoomBy = (amount: number) => {
    this.stopAmbientMotion()
    if (this.state.view === 'turbine') this.localDistance.target = clamp(this.localDistance.target * Math.exp(amount * 0.12), 0.20, 0.78)
    else this.zoom.target = clamp(this.zoom.target * Math.exp(amount * 0.1), 1.38, 4.0)
  }

  rotateBy(x: number, y: number) {
    this.stopAmbientMotion()
    if (this.state.view === 'turbine') {
      this.localAzimuth.target += x * 0.08
      this.localElevation.target = clamp(this.localElevation.target + y * 0.012, -0.025, 0.30)
    } else {
      this.orbitLongitude -= x * 0.06
      this.orbitLatitude = clamp(this.orbitLatitude + y * 0.05, -1.3, 1.3)
    }
  }

  private pointerDown = (event: PointerEvent) => {
    if (event.button !== 0) return
    this.points.set(event.pointerId, new THREE.Vector2(event.clientX, event.clientY))
    this.renderer.domElement.setPointerCapture(event.pointerId)
    this.pointer = { id: event.pointerId, x: event.clientX, y: event.clientY, at: event.timeStamp, moved: false }
    this.orbitVelocity.set(0, 0)
    this.localAzimuth.target = this.localAzimuth.value
    this.localElevation.target = this.localElevation.value
    this.renderer.domElement.classList.add('is-dragging')
    if (this.points.size === 2) { const [a, b] = [...this.points.values()]; this.pinchDistance = a.distanceTo(b) }
  }

  private pointerMove = (event: PointerEvent) => {
    if (!this.points.has(event.pointerId)) return
    this.points.get(event.pointerId)!.set(event.clientX, event.clientY)
    if (this.points.size > 1) {
      const [a, b] = [...this.points.values()]
      const distance = a.distanceTo(b)
      if (this.pinchDistance > 0) this.zoomBy(Math.log(this.pinchDistance / distance) * 8)
      this.pinchDistance = distance
      return
    }
    const pointer = this.pointer
    if (!pointer || pointer.id !== event.pointerId) return
    const dx = event.clientX - pointer.x, dy = event.clientY - pointer.y
    const dt = clamp((event.timeStamp - pointer.at) / 1000, 0.005, 0.06)
    if (this.state.view === 'turbine') {
      this.localAzimuth.value -= dx * 0.005
      this.localAzimuth.target = this.localAzimuth.value
      this.localAzimuth.velocity = -dx * 0.005 / dt
      this.localElevation.value = clamp(this.localElevation.value + dy * 0.0005, -0.025, 0.30)
      this.localElevation.target = this.localElevation.value
    } else {
      const sensitivity = 2.1 / Math.min(this.width, this.height)
      this.orbitLongitude -= dx * sensitivity
      this.orbitLatitude = clamp(this.orbitLatitude + dy * sensitivity, -1.4, 1.4)
      this.orbitVelocity.x = THREE.MathUtils.lerp(this.orbitVelocity.x, -dx * sensitivity / dt, 0.7)
      this.orbitVelocity.y = THREE.MathUtils.lerp(this.orbitVelocity.y, dy * sensitivity / dt, 0.7)
    }
    pointer.x = event.clientX; pointer.y = event.clientY; pointer.at = event.timeStamp; pointer.moved = true
  }

  private pointerUp = (event: PointerEvent) => {
    this.points.delete(event.pointerId)
    if (this.renderer.domElement.hasPointerCapture(event.pointerId)) this.renderer.domElement.releasePointerCapture(event.pointerId)
    if (this.points.size === 0) {
      if (this.state.view === 'turbine' && !this.state.reducedMotion) this.localAzimuth.target += clamp(this.localAzimuth.velocity * 0.16, -0.35, 0.35)
      if (this.state.reducedMotion || !this.pointer || event.timeStamp - this.pointer.at > 90) this.orbitVelocity.set(0, 0)
      this.pointer = null
      this.renderer.domElement.classList.remove('is-dragging')
    } else {
      const [id, point] = [...this.points.entries()][0]
      this.pointer = { id, x: point.x, y: point.y, at: event.timeStamp, moved: true }
    }
  }

  private wheel = (event: WheelEvent) => {
    event.preventDefault()
    this.zoomBy(clamp(event.deltaY * 0.01, -3, 3))
  }

  private visibility = () => {
    this.active = !document.hidden
    this.lastTime = 0
    if (this.active && !this.raf && !this.disposed) this.raf = requestAnimationFrame(this.frame)
  }

  private contextLost = (event: Event) => {
    event.preventDefault()
    this.callbacks.fail()
    cancelAnimationFrame(this.raf)
    this.raf = 0
  }

  private frame = (time: number) => {
    this.raf = 0
    if (this.disposed || !this.active) return
    const rawDelta = this.lastTime ? (time - this.lastTime) / 1000 : 1 / 60
    const dt = clamp(rawDelta, 0.001, 0.05)
    this.lastTime = time
    const reduced = this.state.reducedMotion ?? false
    if (!this.hasInteracted && !reduced && this.state.view === 'earth') this.orbitLongitude += dt * 0.012
    const p = reduced ? this.flight.target : clamp(this.flight.step(dt), 0, 1)
    this.zoom.step(dt)
    this.localAzimuth.step(dt); this.localElevation.step(dt); this.localDistance.step(dt)
    this.anchorLatitude.step(dt); this.anchorLongitude.step(dt)
    if (!this.pointer && p < 0.001 && !reduced) {
      this.orbitLongitude += this.orbitVelocity.x * dt
      this.orbitLatitude = clamp(this.orbitLatitude + this.orbitVelocity.y * dt, -1.4, 1.4)
      this.orbitVelocity.multiplyScalar(Math.exp(-4 * dt))
    }
    this.updateCamera(p)
    const weather = this.weather.update(dt, reduced)
    const lighting = skyLighting(weather)
    const localAmount = smoothstep(0.33, 0.70, p)
    this.sky.mesh.position.copy(this.camera.position)
    this.sky.mesh.quaternion.copy(this.selectedFrame.quaternion)
    this.sky.uniforms.opacity.value = localAmount
    this.sky.uniforms.daylight.value = lighting.daylight
    this.sky.uniforms.sunset.value = lighting.sunset
    this.sky.uniforms.sun.value.copy(lighting.direction)
    this.sky.uniforms.cloud.value = weather.cloudCover
    this.sky.mesh.visible = localAmount > 0.001
    // A single sun vector lights both Earth and the tangent-space environment.
    const worldSun = lighting.direction.applyQuaternion(this.selectedFrame.quaternion)
    if (!this.state.weather) worldSun.set(-0.18, 0.63, -0.75).normalize()
    this.earth.uniforms.sunDirection.value.copy(worldSun)
    this.sun.position.copy(this.selectedFrame.origin).addScaledVector(worldSun, 0.9)
    this.sun.target.position.copy(this.selectedFrame.origin)
    this.sun.intensity = Math.max(0, Math.sin(weather.sunAltitude)) * 5.2 * (1 - weather.cloudCover * 0.72)
    this.sun.color.set('#fff7e7').lerp(new THREE.Color('#ffa365'), lighting.sunset * 0.68)
    this.fill.position.copy(this.selectedFrame.up)
    this.fill.intensity = 0.50 + lighting.daylight * 1.6
    this.fill.color.set('#bddbed').lerp(new THREE.Color('#efceb0'), lighting.sunset * 0.55)
    this.fill.groundColor.set('#738270').lerp(new THREE.Color('#546f9c'), 1 - lighting.daylight)
    // Restrained illustrative night fill keeps the engineering object readable.
    // It is deliberately not a claimed observed moon position or irradiance.
    this.nightFill.position.copy(this.selectedFrame.origin).add(
      this.temp.set(-0.55, 0.48, -0.52).applyQuaternion(this.selectedFrame.quaternion),
    )
    this.nightFill.target.position.copy(this.selectedFrame.origin).addScaledVector(this.selectedFrame.up, 0.065)
    this.nightFill.intensity = 1.25 - lighting.daylight * 0.85
    this.nightFill.color.set('#86a7d3').lerp(new THREE.Color('#fff0cc'), lighting.daylight)
    this.renderer.toneMappingExposure = 1.08 + localAmount * 0.06
    this.earth.atmosphere.visible = p < 0.6
    // The local terrain replaces the globe's coarse surface only after the camera reaches it.
    this.earth.mesh.visible = p < 0.80
    this.local.visible = p > 0.48
    this.renderer.shadowMap.enabled = this.actualQuality !== 'low' && p > 0.72
    this.weatherEffects.update(weather, dt, reduced, this.actualQuality)
    this.terrain?.update(dt, weather.windSpeed, this.state.weather?.windDirection ?? null, reduced, this.actualQuality, lighting.daylight)
    this.weatherEffects.group.position.copy(this.targetWorld).sub(this.localFrame.origin).applyQuaternion(this.localFrame.quaternion.clone().invert())
    for (const item of this.models) {
      // Only the selected turbine has weather. Neighbour rotors are deliberately static.
      const selected = item.site.turbine_id === this.state.selectedSite?.turbine_id
      if (!reduced && selected) item.model.rotor.rotation.z -= weather.rotorSpeed * dt
      if (selected && this.state.weather?.windDirection != null) {
        // The rotor normal faces into the meteorological wind (local +Z is south).
        const target = Math.PI - this.state.weather.windDirection * DEG
        const error = Math.atan2(Math.sin(target - item.model.nacelle.rotation.y), Math.cos(target - item.model.nacelle.rotation.y))
        item.model.nacelle.rotation.y += error * (1 - Math.exp(-dt * 0.65))
      }
      const beaconMaterial = item.model.beacon.material as THREE.MeshStandardMaterial
      beaconMaterial.emissiveIntensity = 0.1 + (1 - lighting.daylight) * 0.8
    }
    const fogDistance = Math.max(0.3, weather.visibility / 1000)
    if (p > 0.55) {
      if (!(this.scene.fog instanceof THREE.FogExp2)) this.scene.fog = new THREE.FogExp2('#a6aba5', 0.01)
      this.scene.fog.color.set('#9cc9d4').multiplyScalar(0.20 + lighting.daylight * 0.80)
      this.scene.fog.density = localAmount * (0.009 + 1 / fogDistance * 0.15)
    } else this.scene.fog = null
    this.updateMarkers(p)
    this.renderer.render(this.scene, this.camera)
    if (!this.ready) { this.ready = true; this.callbacks.ready() }
    this.adaptQuality(rawDelta, time)
    this.raf = requestAnimationFrame(this.frame)
  }

  private updateCamera(p: number) {
    const globalNormal = earthPoint(this.orbitLatitude / DEG, this.orbitLongitude / DEG, 1)
    const frame = surfaceFrame({ latitude: this.anchorLatitude.value, longitude: this.anchorLongitude.value })
    this.targetWorld.copy(this.selectedFrame.origin)
    if (p < 0.0001) {
      this.camera.position.copy(globalNormal).multiplyScalar(EARTH_RADIUS * this.zoom.value * Math.max(1, this.height / this.width))
      this.camera.up.set(0, 1, 0)
      this.camera.lookAt(0, 0, 0)
    } else {
      const align = smoothstep(0, 0.58, p)
      sphericalDirection(this.flightStartNormal, frame.up, align, this.temp)
      const altitude = this.flightStartAltitude * Math.pow((0.085 + this.localElevation.value) / this.flightStartAltitude, p)
      this.camera.position.copy(this.temp).multiplyScalar(EARTH_RADIUS + altitude)
      const distance = this.localDistance.value * smoothstep(0.55, 0.98, p)
      this.temp2.set(Math.sin(this.localAzimuth.value) * distance, 0, Math.cos(this.localAzimuth.value) * distance)
        .applyQuaternion(frame.quaternion)
      this.camera.position.add(this.temp2)
      this.camera.up.set(0, 1, 0).lerp(frame.up, smoothstep(0.15, 0.75, p)).normalize()
      this.temp.copy(frame.origin).multiplyScalar(smoothstep(0, 0.45, p))
      this.temp.addScaledVector(frame.up, 0.067 * smoothstep(0.6, 1, p))
      this.camera.lookAt(this.temp)
    }
    // Framing leaves space for the interface, not another dashboard column.
    const mobile = this.width < 700
    const shift = mobile ? 0.04 * p : 0.115 - 0.035 * p
    this.camera.fov = 42 + 30 * smoothstep(0.5, 1, p)
    this.camera.setViewOffset(this.width, this.height, -this.width * shift, 0, this.width, this.height)
    this.camera.updateMatrixWorld()
  }

  private updateMarkers(p: number) {
    if (p > 0.68) { this.callbacks.markers(this.emptyMarkers); return }
    const points: MarkerProjection[] = this.state.sites.map(site => {
      const world = earthPoint(site.latitude, site.longitude, EARTH_RADIUS + 1)
      const facing = world.dot(this.temp.copy(this.camera.position).sub(world)) > 0
      this.projection.copy(world).project(this.camera)
      const x = (this.projection.x + 1) * this.width / 2
      const y = (1 - this.projection.y) * this.height / 2
      return { id: site.turbine_id, x, y, anchorX: x, anchorY: y,
        visible: facing && this.projection.z < 1 && x > 30 && x < this.width - 30 && y > 65 && y < this.height - 80 }
    })
    // Adjacent real sites share a pixel at orbital scale. Fan labels, retain the true anchor.
    const placed: MarkerProjection[] = []
    for (const point of points) {
      if (!point.visible) continue
      const cluster = points.filter(other => other.visible && Math.hypot(other.anchorX - point.anchorX, other.anchorY - point.anchorY) < 70)
      if (cluster.length > 1) {
        const index = cluster.indexOf(point)
        point.x += (index - (cluster.length - 1) / 2) * 62
        point.y -= 31
      }
      if (placed.some(other => Math.hypot(other.x - point.x, other.y - point.y) < 48)) point.y -= 56
      placed.push(point)
    }
    this.callbacks.markers(points)
  }

  private adaptQuality(delta: number, time: number) {
    if (this.state.quality && this.state.quality !== 'auto') return
    if (delta > 0.5) return
    this.frameSum += Math.min(delta, 0.12); this.frameCount += 1
    if (this.frameCount < 150 || time - this.qualityAt < 6000) return
    const mean = this.frameSum / this.frameCount
    this.frameSum = 0; this.frameCount = 0; this.qualityAt = time
    if (mean > 0.029 && this.actualQuality !== 'low') this.setQuality(this.actualQuality === 'high' ? 'medium' : 'low')
  }

  dispose() {
    this.disposed = true
    cancelAnimationFrame(this.raf)
    this.resizeObserver.disconnect()
    document.removeEventListener('visibilitychange', this.visibility)
    document.removeEventListener('pointerdown', this.stopAmbientMotion, true)
    document.removeEventListener('keydown', this.stopAmbientMotion, true)
    const canvas = this.renderer.domElement
    canvas.removeEventListener('pointerdown', this.pointerDown)
    canvas.removeEventListener('pointermove', this.pointerMove)
    canvas.removeEventListener('pointerup', this.pointerUp)
    canvas.removeEventListener('pointercancel', this.pointerUp)
    canvas.removeEventListener('wheel', this.wheel)
    canvas.removeEventListener('webglcontextlost', this.contextLost)
    disposeObject(this.scene)
    this.sun.shadow.map?.dispose()
    this.renderer.dispose()
    canvas.remove()
  }
}
