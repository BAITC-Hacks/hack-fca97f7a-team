import * as THREE from 'three'
import { windVisualProfile } from './wind'

export interface TurbineModel {
  group: THREE.Group
  rotor: THREE.Group
  nacelle: THREE.Group
  beacon: THREE.Mesh
}

function airfoilBlade() {
  const positions: number[] = [], indices: number[] = []
  const segments = 30, ring = 12
  for (let row = 0; row <= segments; row++) {
    const t = row / segments
    const y = 2.4 + t * 50
    const chord = (3.55 * Math.pow(1 - t, 0.6) + 0.04) * Math.min(1, 0.5 + t * 8)
    const twist = (1 - t) * 0.38
    const sweep = -Math.pow(t, 2.7) * 2.5
    for (let side = 0; side < ring; side++) {
      const a = side / ring * Math.PI * 2
      const x = Math.cos(a) * chord * 0.5
      const z = Math.sin(a) * chord * (0.14 * (1 - t) + 0.045)
      positions.push(x * Math.cos(twist) - z * Math.sin(twist) + sweep,
        y, x * Math.sin(twist) + z * Math.cos(twist) + t * t * 0.75)
      if (row < segments) {
        const i = row * ring + side, j = row * ring + (side + 1) % ring
        indices.push(i, i + ring, j, j, i + ring, j + ring)
      }
    }
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  geometry.setIndex(indices)
  geometry.computeVertexNormals()
  return geometry
}

/** Original, efficient engineering illustration; not a claimed make/model or surveyed dimensions. */
export function createTurbine(id: string): TurbineModel {
  const group = new THREE.Group()
  group.name = `Турбина ${id}`
  group.scale.setScalar(0.001)
  const white = new THREE.MeshStandardMaterial({ color: '#fff9e9', roughness: 0.47, metalness: 0.10 })
  const steel = new THREE.MeshStandardMaterial({ color: '#8d9697', roughness: 0.65, metalness: 0.6 })
  const dark = new THREE.MeshStandardMaterial({ color: '#27343a', roughness: 0.6 })
  const concrete = new THREE.MeshStandardMaterial({ color: '#9c9a8e', roughness: 0.98 })
  const mesh = (geometry: THREE.BufferGeometry, material: THREE.Material, parent: THREE.Group = group) => {
    const item = new THREE.Mesh(geometry, material)
    item.castShadow = true; item.receiveShadow = true
    parent.add(item)
    return item
  }

  const base = mesh(new THREE.CylinderGeometry(5.3, 6.5, 0.8, 32), concrete)
  base.position.y = 0.4
  const tower = mesh(new THREE.CylinderGeometry(1.65, 2.7, 92, 40, 8), white)
  tower.position.y = 46.5
  for (const height of [1.2, 26, 54, 78, 92]) {
    const radius = 2.7 - (height / 92) * 1.05 + 0.023
    const seam = mesh(new THREE.CylinderGeometry(radius, radius, 0.13, 40), steel)
    seam.position.y = height
  }
  const door = mesh(new THREE.BoxGeometry(1.05, 2.4, 0.10), dark)
  door.position.set(0, 2.3, 2.65)
  const step = mesh(new THREE.BoxGeometry(1.5, 0.25, 0.8), steel)
  step.position.set(0, 0.85, 3)
  // Muted mint base band gives the object a readable edge without a game-like accent.
  const band = mesh(new THREE.CylinderGeometry(2.69, 2.7, 0.36, 40), new THREE.MeshStandardMaterial({ color: '#93a69c', roughness: 0.65 }))
  band.position.y = 1.08

  const nacelle = new THREE.Group()
  nacelle.position.y = 94
  group.add(nacelle)
  const body = mesh(new THREE.CapsuleGeometry(2.3, 6.7, 8, 20), white, nacelle)
  body.rotation.x = Math.PI / 2
  body.position.z = -1.5
  const underside = mesh(new THREE.BoxGeometry(2.8, 0.65, 6), steel, nacelle)
  underside.position.set(0, -2, -1.1)
  const ventMaterial = new THREE.MeshStandardMaterial({ color: '#596065', roughness: 0.7 })
  for (let i = 0; i < 6; i++) {
    const vent = mesh(new THREE.BoxGeometry(0.08, 1.2, 2.6), ventMaterial, nacelle)
    vent.position.set(2.23, 0.5, -3.5 + i * 0.35)
    vent.scale.z = 0.075
  }
  const service = mesh(new THREE.BoxGeometry(2.5, 0.08, 4.5), steel, nacelle)
  service.position.set(0, 2.33, -2)
  // Roof anemometer and maintenance rails are visible during close orbit.
  for (const x of [-1.2, 1.2]) {
    const rail = mesh(new THREE.CylinderGeometry(0.045, 0.045, 3.8, 6), steel, nacelle)
    rail.rotation.x = Math.PI / 2; rail.position.set(x, 2.9, -2)
    for (const z of [-3.6, -0.4]) {
      const post = mesh(new THREE.CylinderGeometry(0.045, 0.045, 0.6, 6), steel, nacelle)
      post.position.set(x, 2.65, z)
    }
  }
  const mast = mesh(new THREE.CylinderGeometry(0.055, 0.055, 1.8, 8), steel, nacelle)
  mast.position.set(0, 3.05, -4)
  const sensor = mesh(new THREE.BoxGeometry(0.9, 0.12, 0.12), dark, nacelle)
  sensor.position.set(0, 3.93, -4)

  const rotor = new THREE.Group()
  rotor.position.z = 4.35
  rotor.rotation.z = 0.35
  nacelle.add(rotor)
  const bladeGeometry = airfoilBlade()
  for (let i = 0; i < 3; i++) {
    const blade = mesh(bladeGeometry, white, rotor)
    blade.rotation.z = i * Math.PI * 2 / 3
  }
  const hub = mesh(new THREE.SphereGeometry(2.7, 24, 16), white, rotor)
  hub.scale.set(1, 1, 1.5); hub.position.z = 0.35
  const beaconMaterial = new THREE.MeshStandardMaterial({ color: '#b85545', emissive: '#df5a45', emissiveIntensity: 0.12 })
  const beacon = mesh(new THREE.SphereGeometry(0.17, 10, 8), beaconMaterial, nacelle)
  beacon.position.set(0.8, 2.68, -0.8)
  nacelle.rotation.y = 3.4
  return { group, rotor, nacelle, beacon }
}

function terrainHeight(x: number, z: number) {
  const distance = Math.hypot(x, z)
  const foothills = Math.max(0, Math.min(1, (distance - 0.65) / 4))
  const waves = Math.sin(x * 0.9 + Math.sin(z * 0.6)) * 0.045 + Math.cos(z * 0.8 - x * 0.2) * 0.035
  const ridge = Math.pow(Math.max(0, Math.sin(x * 0.14 + z * 0.08 + 0.7)), 3) * 0.25
  const detail = Math.sin(x * 4.1) * Math.cos(z * 3.4) * 0.010
  return (waves + ridge + detail + 0.025) * foothills - distance * distance / (2 * 6371)
}

function groundMaterial(night: { value: number }) {
  const material = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 1, metalness: 0 })
  material.onBeforeCompile = shader => {
    shader.uniforms.groundNight = night
    shader.vertexShader = `varying vec3 vGroundPoint;\n${shader.vertexShader}`.replace(
      '#include <begin_vertex>', '#include <begin_vertex>\nvGroundPoint = position;',
    )
    shader.fragmentShader = `uniform float groundNight; varying vec3 vGroundPoint;
      float groundHash(vec2 p) { return fract(sin(dot(p,vec2(127.1,311.7))) * 43758.5453123); }
      float groundNoise(vec2 p) {
        vec2 cell=floor(p), f=fract(p); f=f*f*(3.0-2.0*f);
        return mix(mix(groundHash(cell),groundHash(cell+vec2(1.,0.)),f.x),
          mix(groundHash(cell+vec2(0.,1.)),groundHash(cell+vec2(1.)),f.x),f.y);
      }
      ${shader.fragmentShader}`.replace('#include <color_fragment>', `#include <color_fragment>
        float groundDetail = groundNoise(vGroundPoint.xz*240.0)*0.55 + groundNoise(vGroundPoint.xz*870.0)*0.30 + groundNoise(vGroundPoint.xz*34.0)*0.15;
        diffuseColor.rgb *= mix(0.92,1.08,groundDetail);
        float groundLuminance = dot(diffuseColor.rgb, vec3(0.2126,0.7152,0.0722));
        diffuseColor.rgb = mix(diffuseColor.rgb, groundLuminance * vec3(0.33,0.53,0.78), groundNight);
      `)
  }
  material.customProgramCacheKey = () => 'samal-terrain-v2'
  return material
}

function createLandscapeMotion(heightAt: (x: number, z: number) => number, neighbours: THREE.Vector3[]) {
  const group = new THREE.Group()
  const positions: number[] = [], uvs: number[] = [], indices: number[] = []
  for (let blade = 0; blade < 3; blade++) {
    const angle = blade * Math.PI / 3
    for (let row = 0; row < 3; row++) {
      const t = row / 2, width = (1 - t * 0.95) * 0.00026
      for (const side of [-1, 1]) {
        const x = side * width, z = t * t * 0.00019
        positions.push(x * Math.cos(angle) - z * Math.sin(angle), t * 0.00085,
          x * Math.sin(angle) + z * Math.cos(angle))
        uvs.push((side + 1) / 2, t)
      }
      if (row < 2) {
        const start = blade * 6 + row * 2
        indices.push(start, start + 2, start + 1, start + 1, start + 2, start + 3)
      }
    }
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2))
  geometry.setIndex(indices); geometry.computeVertexNormals()
  const uniforms = { time: { value: 0 }, strength: { value: 0 }, night: { value: 0 } }
  const material = new THREE.MeshStandardMaterial({ color: '#ffffff', side: THREE.DoubleSide, roughness: 0.9, emissive: '#739d54', emissiveIntensity: 0.12 })
  material.onBeforeCompile = shader => {
    shader.uniforms.grassTime = uniforms.time
    shader.uniforms.grassWind = uniforms.strength
    shader.uniforms.grassNight = uniforms.night
    shader.vertexShader = `uniform float grassTime; uniform float grassWind; varying float vBladeHeight;\n${shader.vertexShader}`
      .replace('#include <begin_vertex>', `#include <begin_vertex>
        vBladeHeight = uv.y;
        float phase = instanceMatrix[3].x * 57.0 + instanceMatrix[3].z * 39.0;
        float sway = sin(grassTime * 1.65 + phase) * 0.7 + sin(grassTime * 0.73 + phase*0.43) * 0.3;
        transformed.x += (0.00025 + sway * 0.00065) * grassWind * uv.y * uv.y;
        transformed.z += cos(grassTime * 1.2 + phase) * grassWind * uv.y * uv.y * 0.00025;
      `)
    shader.fragmentShader = `uniform float grassNight; varying float vBladeHeight;\n${shader.fragmentShader}`
      .replace('#include <color_fragment>', `#include <color_fragment>
        diffuseColor.rgb *= mix(0.95, 1.15, vBladeHeight);
        float grassLuminance = dot(diffuseColor.rgb, vec3(0.2126,0.7152,0.0722));
        diffuseColor.rgb = mix(diffuseColor.rgb, grassLuminance * vec3(0.33,0.53,0.78), grassNight);
      `)
  }
  material.customProgramCacheKey = () => 'samal-grass-v2'
  const count = 14000
  const grass = new THREE.InstancedMesh(geometry, material, count)
  const dummy = new THREE.Object3D()
  const green = new THREE.Color('#92b66c'), gold = new THREE.Color('#c8bc7c')
  const colour = new THREE.Color()
  const random = (value: number) => { const n = Math.sin(value * 127.1 + 311.7) * 43758.5453; return n - Math.floor(n) }
  let written = 0
  for (let i = 0; written < count && i < count * 2; i++) {
    const x = (random(i * 4 + 1) - 0.5) * 0.85
    const z = (random(i * 4 + 2) - 0.5) * 0.85
    const radial = Math.max(0, 1 - Math.hypot(x, z) / 0.43)
    if (radial === 0) continue
    if (neighbours.some(point => Math.hypot(x - point.x, z - point.z) < 0.025)) continue
    dummy.position.set(x, heightAt(x, z), z)
    dummy.rotation.y = random(i * 4 + 3) * Math.PI * 2
    // Soft circular falloff and broad meadow patches avoid a rectangular turf edge.
    const meadow = 0.35 + 0.65 * Math.pow(0.5 + 0.5 * Math.sin(x * 29 + Math.sin(z * 23)), 2)
    dummy.scale.setScalar((0.7 + random(i * 4 + 4) * 1.2) * Math.min(1, radial * 5) * meadow)
    dummy.updateMatrix()
    grass.setMatrixAt(written, dummy.matrix)
    colour.copy(green).lerp(gold, Math.pow(random(i * 7.9), 2) * 0.85)
    grass.setColorAt(written, colour)
    written += 1
  }
  grass.count = written
  grass.instanceMatrix.needsUpdate = true
  if (grass.instanceColor) grass.instanceColor.needsUpdate = true
  grass.computeBoundingSphere()
  group.add(grass)

  const dustGeometry = new THREE.BufferGeometry()
  const dustPositions = new Float32Array(192 * 3)
  for (let i = 0; i < 192; i++) dustPositions.set([(random(i * 3) - 0.5) * 0.9, 0.006 + random(i * 3 + 1) * 0.145, (random(i * 3 + 2) - 0.5) * 0.9], i * 3)
  dustGeometry.setAttribute('position', new THREE.BufferAttribute(dustPositions, 3))
  const dustMaterial = new THREE.PointsMaterial({ color: '#f9e6b4', size: 1.4, sizeAttenuation: false, transparent: true, opacity: 0.16, depthWrite: false })
  dustMaterial.onBeforeCompile = shader => {
    shader.fragmentShader = shader.fragmentShader.replace('#include <opaque_fragment>', `
      float pointRadius = length(gl_PointCoord - vec2(0.5));
      diffuseColor.a *= 1.0 - smoothstep(0.15,0.5,pointRadius);
      #include <opaque_fragment>
    `)
  }
  dustMaterial.customProgramCacheKey = () => 'samal-wind-points-v1'
  const dust = new THREE.Points(dustGeometry, dustMaterial)
  dust.name = 'Художественные частицы воздушного потока'
  dust.frustumCulled = false; group.add(dust)
  // One instanced draw keeps strong wind legible without a particle wall or postprocessing.
  const ribbonGeometry = new THREE.PlaneGeometry(1, 1, 32, 1)
  const ribbonUniforms = { width: { value: 0.001 }, curve: { value: 0.004 }, time: uniforms.time }
  const ribbonMaterial = new THREE.MeshBasicMaterial({
    color: '#f3f7df', side: THREE.DoubleSide, transparent: true, opacity: 0,
    depthWrite: false, toneMapped: false,
  })
  ribbonMaterial.onBeforeCompile = shader => {
    shader.uniforms.flowWidth = ribbonUniforms.width
    shader.uniforms.flowCurve = ribbonUniforms.curve
    shader.uniforms.flowTime = ribbonUniforms.time
    shader.vertexShader = `uniform float flowWidth; uniform float flowCurve; uniform float flowTime; varying vec2 vFlowUv;\n${shader.vertexShader}`
      .replace('#include <begin_vertex>', `#include <begin_vertex>
        vFlowUv = uv;
        float phase = instanceMatrix[3].y * 35.0 + instanceMatrix[3].z * 5.0;
        transformed.y = position.y * flowWidth + sin(uv.x * 4.0 + phase + flowTime * 0.25) * flowCurve;
        transformed.z += sin(uv.x * 3.2 + phase) * flowCurve * 0.35;
      `)
    shader.fragmentShader = `varying vec2 vFlowUv;\n${shader.fragmentShader}`
      .replace('#include <color_fragment>', `#include <color_fragment>
        float along = smoothstep(0.0,0.22,vFlowUv.x) * (1.0 - smoothstep(0.55,1.0,vFlowUv.x));
        float across = pow(max(0.0,1.0 - abs(vFlowUv.y-0.5)*2.0),1.6);
        diffuseColor.a *= along * across;
      `)
  }
  ribbonMaterial.customProgramCacheKey = () => 'samal-wind-ribbons-v1'
  const ribbons = new THREE.InstancedMesh(ribbonGeometry, ribbonMaterial, 24)
  ribbons.name = 'Художественные линии воздушного потока'
  ribbons.instanceMatrix.setUsage(THREE.DynamicDrawUsage)
  ribbons.frustumCulled = false
  const ribbonPositions = Array.from({ length: 24 }, (_, i) => new THREE.Vector3(
    (random(i + 50) - 0.5) * 0.85, 0.014 + random(i + 70) * 0.14, (random(i + 90) - 0.5) * 0.85,
  ))
  const ribbonTransform = new THREE.Object3D()
  group.add(ribbons)
  return {
    group,
    update(delta: number, wind: number, bearing: number | null, reduced: boolean, quality: string, daylight: number) {
      const flow = windVisualProfile(wind, reduced, quality)
      uniforms.night.value = 1 - daylight
      material.emissiveIntensity = daylight * 0.12
      uniforms.strength.value = flow.strength
      if (!reduced && flow.speed > 0) uniforms.time.value += delta * flow.speed * 0.14
      grass.count = quality === 'low' ? 0 : quality === 'medium' ? Math.min(written, 6500) : written
      dust.visible = flow.particles > 0; ribbons.visible = flow.ribbons > 0
      dustGeometry.setDrawRange(0, flow.particles)
      dustMaterial.opacity = flow.opacity * (0.6 + daylight * 0.4)
      dustMaterial.size = 1.25 + flow.strength * 1.15
      ribbons.count = flow.ribbons
      ribbonMaterial.opacity = flow.opacity * (0.75 + daylight * 0.25)
      ribbonUniforms.width.value = flow.width
      ribbonUniforms.curve.value = 0.002 + flow.strength * 0.004
      if (!flow.ribbons) return
      // Absent bearing is an expressly illustrative, curved drift, not telemetry.
      const direction = bearing == null ? 0.2 : bearing * Math.PI / 180 + Math.PI / 2
      const dx = Math.cos(direction) * flow.speed * 0.001 * delta
      const dz = Math.sin(direction) * flow.speed * 0.001 * delta
      for (let i = 0; i < 192; i++) {
        dustPositions[i * 3] += dx
        dustPositions[i * 3 + 2] += dz
        if (dustPositions[i * 3] > 0.5) dustPositions[i * 3] -= 1
        if (dustPositions[i * 3] < -0.5) dustPositions[i * 3] += 1
        if (dustPositions[i * 3 + 2] > 0.5) dustPositions[i * 3 + 2] -= 1
        if (dustPositions[i * 3 + 2] < -0.5) dustPositions[i * 3 + 2] += 1
      }
      dustGeometry.attributes.position.needsUpdate = true
      for (let i = 0; i < ribbonPositions.length; i++) {
        const position = ribbonPositions[i]
        position.x += dx; position.z += dz
        if (position.x > 0.5) position.x -= 1
        if (position.x < -0.5) position.x += 1
        if (position.z > 0.5) position.z -= 1
        if (position.z < -0.5) position.z += 1
        ribbonTransform.position.copy(position)
        ribbonTransform.rotation.y = -direction
        ribbonTransform.scale.set(flow.length * (0.75 + random(i + 120) * 0.5), 1, 1)
        ribbonTransform.updateMatrix()
        ribbons.setMatrixAt(i, ribbonTransform.matrix)
      }
      ribbons.instanceMatrix.needsUpdate = true
    },
  }
}

export function createTerrain(neighbours: THREE.Vector3[]) {
  const group = new THREE.Group()
  const geometry = new THREE.PlaneGeometry(100, 100, 192, 192)
  geometry.rotateX(-Math.PI / 2)
  const pos = geometry.attributes.position
  const colors = new Float32Array(pos.count * 3)
  const color = new THREE.Color()
  const steppe = new THREE.Color('#79a958'), hills = new THREE.Color('#4f8955'), rock = new THREE.Color('#c3ae6e')
  const heightAt = (x: number, z: number) => {
    let y = terrainHeight(x, z)
    for (const point of neighbours) {
      const d = Math.hypot(x - point.x, z - point.z)
      const flat = Math.exp(-d * d / 0.20)
      y = y * (1 - flat) + point.y * flat
    }
    return y
  }
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i), z = pos.getZ(i)
    const y = heightAt(x, z)
    pos.setY(i, y)
    const patch = (Math.sin(x * 0.37 + z * 0.21) + Math.cos(z * 0.28 + Math.sin(x * 0.17))) * 0.035 + 0.27
    color.copy(steppe).lerp(hills, patch).lerp(rock, Math.max(0, y) * 0.4)
    colors.set([color.r, color.g, color.b], i * 3)
  }
  // The dense centre REPLACES coarse triangles. Overlapping coarse/fine ground
  // produced visible triangular depth fighting at kilometre-to-metre scales.
  const nearSpan = 100 / 192 * 6
  const halfNear = nearSpan / 2
  const originalIndex = geometry.getIndex()!
  const kept: number[] = []
  for (let i = 0; i < originalIndex.count; i += 3) {
    const a = originalIndex.getX(i), b = originalIndex.getX(i + 1), c = originalIndex.getX(i + 2)
    const x = (pos.getX(a) + pos.getX(b) + pos.getX(c)) / 3
    const z = (pos.getZ(a) + pos.getZ(b) + pos.getZ(c)) / 3
    if (Math.abs(x) < halfNear && Math.abs(z) < halfNear) continue
    kept.push(a, b, c)
  }
  geometry.setIndex(kept)
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3))
  geometry.computeVertexNormals()
  const night = { value: 0 }
  const material = groundMaterial(night)
  const ground = new THREE.Mesh(geometry, material)
  ground.receiveShadow = true
  group.add(ground)
  // A near-field patch adds ground detail without a satellite-geometry claim.
  const nearGeometry = new THREE.PlaneGeometry(nearSpan, nearSpan, 120, 120)
  nearGeometry.rotateX(-Math.PI / 2)
  const nearPos = nearGeometry.attributes.position
  const nearColors = new Float32Array(nearPos.count * 3)
  for (let i = 0; i < nearPos.count; i++) {
    const x = nearPos.getX(i), z = nearPos.getZ(i)
    const small = Math.sin(x * 110 + z * 49) * Math.cos(x * 57 - z * 83)
    const d = Math.min(...neighbours.map(p => Math.hypot(x - p.x, z - p.z)))
    const height = heightAt(x, z)
    // The outer edge must follow the coarse mesh's piecewise-linear surface,
    // not a new sample of the curved height function, otherwise a sky gap opens.
    const cell = 100 / 192
    const x0 = Math.floor((x + 50) / cell) * cell - 50
    const z0 = Math.floor((z + 50) / cell) * cell - 50
    const fx = (x - x0) / cell, fz = (z - z0) / cell
    const h00 = heightAt(x0, z0), h10 = heightAt(x0 + cell, z0)
    const h01 = heightAt(x0, z0 + cell), h11 = heightAt(x0 + cell, z0 + cell)
    const coarse = fx + fz <= 1
      ? h00 + (h10 - h00) * fx + (h01 - h00) * fz
      : h11 + (h01 - h11) * (1 - fx) + (h10 - h11) * (1 - fz)
    const edge = Math.max(0, Math.min(1, (Math.max(Math.abs(x), Math.abs(z)) - halfNear + 0.15) / 0.15))
    nearPos.setY(i, height * (1 - edge) + coarse * edge + small * 0.00007 * Math.min(1, d / 0.02) * (1 - edge))
    const patch = (Math.sin(x * 0.37 + z * 0.21) + Math.cos(z * 0.28 + Math.sin(x * 0.17))) * 0.035 + 0.27
    color.copy(steppe).lerp(hills, patch).lerp(rock, Math.max(0, height) * 0.4)
    nearColors.set([color.r, color.g, color.b], i * 3)
  }
  nearGeometry.setAttribute('color', new THREE.BufferAttribute(nearColors, 3))
  nearGeometry.computeVertexNormals()
  const near = new THREE.Mesh(nearGeometry, material)
  near.receiveShadow = true; group.add(near)

  const roadMaterial = new THREE.MeshStandardMaterial({ color: '#a59e84', roughness: 1 })
  for (const point of neighbours) {
    const route = new THREE.CatmullRomCurve3([
      new THREE.Vector3(point.x, point.y + 0.0003, point.z + 0.009),
      new THREE.Vector3(point.x + 0.018, 0.0004, point.z + 0.035),
      new THREE.Vector3(point.x + 0.15, 0.0004, point.z + 0.1),
      new THREE.Vector3(point.x + 0.4, 0.0004, point.z + 0.48),
    ])
    const road = new THREE.Mesh(new THREE.TubeGeometry(route, 40, 0.003, 3, false), roadMaterial)
    road.scale.y = 0.1; road.receiveShadow = true; group.add(road)
    const pad = new THREE.Mesh(new THREE.CircleGeometry(0.014, 32), roadMaterial)
    pad.rotation.x = -Math.PI / 2; pad.position.copy(point); pad.position.y += 0.0001
    pad.receiveShadow = true; group.add(pad)
  }
  const landscape = createLandscapeMotion(heightAt, neighbours)
  group.add(landscape.group)
  return { group, update(delta: number, wind: number, bearing: number | null, reduced: boolean, quality: string, daylight: number) {
    night.value = 1 - daylight
    landscape.update(delta, wind, bearing, reduced, quality, daylight)
  } }
}
