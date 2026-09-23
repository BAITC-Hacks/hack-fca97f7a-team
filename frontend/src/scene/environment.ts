import * as THREE from 'three'
import { EARTH_RADIUS } from './geography'
import type { VisualWeather } from '../experience/weather'
import { smoothstep } from '../experience/weather'

export function createEarth() {
  const uniforms = { surface: { value: null as THREE.Texture | null }, sunDirection: { value: new THREE.Vector3(1, 0.6, 0) }, textured: { value: 0 } }
  const material = new THREE.ShaderMaterial({
    uniforms,
    vertexShader: `
      varying vec2 vUv; varying vec3 vNormal;
      #include <common>
      #include <logdepthbuf_pars_vertex>
      void main() {
        vUv = uv; vNormal = normalize(mat3(modelMatrix) * normal);
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        #include <logdepthbuf_vertex>
      }`,
    fragmentShader: `
      uniform sampler2D surface; uniform vec3 sunDirection; uniform float textured;
      varying vec2 vUv; varying vec3 vNormal;
      #include <common>
      #include <logdepthbuf_pars_fragment>
      void main() {
        #include <logdepthbuf_fragment>
        vec3 albedo = mix(vec3(0.026, 0.075, 0.115), texture2D(surface, vUv).rgb, textured);
        // The NASA surface composite is intentionally left geographically exact;
        // restrained saturation avoids an oversaturated green/blue globe.
        float luminance = dot(albedo, vec3(0.2126,0.7152,0.0722));
        albedo = mix(vec3(luminance), albedo, 0.84);
        float diffuse = dot(normalize(vNormal), normalize(sunDirection));
        float daylight = smoothstep(-0.1, 0.16, diffuse);
        vec3 day = albedo * (0.38 + 0.83 * max(0.0, diffuse));
        vec3 night = albedo * vec3(0.045, 0.066, 0.095);
        gl_FragColor = vec4(mix(night, day, daylight), 1.0);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  })
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(EARTH_RADIUS, 128, 80), material)
  mesh.name = 'Земля · NASA Blue Marble'
  const atmosphere = new THREE.Mesh(new THREE.SphereGeometry(EARTH_RADIUS * 1.011, 96, 64), new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, uniforms: { sunDirection: uniforms.sunDirection, strength: { value: 1 } },
    vertexShader: `
      varying vec3 vNormal; varying vec3 vPosition;
      #include <common>
      #include <logdepthbuf_pars_vertex>
      void main() {
        vNormal = normalize(mat3(modelMatrix) * normal); vPosition = (modelMatrix * vec4(position, 1.0)).xyz;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        #include <logdepthbuf_vertex>
      }`,
    fragmentShader: `
      uniform vec3 sunDirection; uniform float strength; varying vec3 vNormal; varying vec3 vPosition;
      #include <common>
      #include <logdepthbuf_pars_fragment>
      void main() {
        #include <logdepthbuf_fragment>
        float rim = pow(1.0 - max(0.0, dot(normalize(vNormal), normalize(cameraPosition - vPosition))), 3.7);
        float daylight = smoothstep(-0.4, 0.4, dot(normalize(vNormal), normalize(sunDirection)));
        gl_FragColor = vec4(mix(vec3(0.05,0.12,0.22), vec3(0.25,0.55,0.88), daylight), rim * (0.10 + daylight * 0.29) * strength);
        #include <colorspace_fragment>
      }`,
  }))
  atmosphere.renderOrder = 2
  return { mesh, atmosphere, uniforms }
}

export function createSky() {
  const uniforms = {
    sun: { value: new THREE.Vector3(-1, 0.5, 0) }, daylight: { value: 1 }, sunset: { value: 0 },
    opacity: { value: 0 }, cloud: { value: 0 },
  }
  const material = new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false, depthTest: false, uniforms,
    vertexShader: `varying vec3 vDirection; void main() { vDirection = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
    fragmentShader: `
      varying vec3 vDirection; uniform vec3 sun; uniform float daylight; uniform float sunset; uniform float opacity; uniform float cloud;
      float hash(vec3 p) { return fract(sin(dot(p, vec3(127.1,311.7,74.7))) * 43758.5453); }
      void main() {
        vec3 d = normalize(vDirection);
        float horizon = exp(-max(0.0,d.y) * 9.0);
        vec3 zenith = mix(vec3(0.016,0.036,0.075), vec3(0.055,0.28,0.66), daylight);
        vec3 low = mix(vec3(0.045,0.075,0.14), vec3(0.44,0.70,0.80), daylight);
        float facingSun = pow(max(0.0, dot(normalize(vec3(d.x,0.,d.z)), normalize(vec3(sun.x,0.,sun.z)))), 3.0);
        low = mix(low, vec3(0.97,0.51,0.22), sunset * facingSun * 0.75);
        vec3 sky = mix(zenith, low, horizon);
        sky = mix(sky, vec3(0.3,0.34,0.38) * (0.15 + daylight*0.7), cloud * 0.65);
        float alignment = dot(d, normalize(sun));
        float disk = smoothstep(0.999960,0.999985,alignment) * smoothstep(-0.03,0.02,sun.y);
        float halo = pow(max(0.0,alignment),34.0) * 0.48 * daylight;
        vec3 tangent = normalize(cross(normalize(sun), vec3(0.01,1.0,0.0)));
        vec3 bitangent = cross(normalize(sun), tangent);
        float around = atan(dot(d,bitangent),dot(d,tangent));
        float rays = pow(0.5 + 0.5*sin(around*9.0+0.7),10.0) * pow(max(0.0,alignment),7.0);
        rays *= smoothstep(-0.02,0.14,sun.y) * daylight * 0.12;
        sky += vec3(1.0,0.80,0.47) * (disk * 1.6 + halo + rays) * (1.0 - cloud*0.8);
        float star = step(0.9984,hash(floor(d*900.0))) * (1.0 - daylight) * smoothstep(0.04,0.45,d.y);
        sky += star * 0.18;
        gl_FragColor = vec4(sky * opacity, 1.0);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  })
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(300, 32, 24), material)
  mesh.renderOrder = -100
  mesh.frustumCulled = false
  return { mesh, uniforms }
}

/** Real cloud/rain fields may enable these effects later. Unknown values remain visually absent. */
export function createWeatherEffects() {
  const group = new THREE.Group()
  const clouds = new THREE.Group()
  const cloudCanvas = document.createElement('canvas')
  cloudCanvas.width = 128; cloudCanvas.height = 128
  const context = cloudCanvas.getContext('2d')!
  const gradient = context.createRadialGradient(64, 64, 0, 64, 64, 62)
  gradient.addColorStop(0, 'rgba(255,255,255,0.5)')
  gradient.addColorStop(0.45, 'rgba(255,255,255,0.18)')
  gradient.addColorStop(1, 'rgba(255,255,255,0)')
  context.fillStyle = gradient; context.fillRect(0, 0, 128, 128)
  const texture = new THREE.CanvasTexture(cloudCanvas)
  const cloudMaterial = new THREE.SpriteMaterial({ map: texture, opacity: 0, depthWrite: false, color: '#d7e0e3', fog: true })
  for (let i = 0; i < 25; i++) {
    const cloud = new THREE.Sprite(cloudMaterial)
    const angle = i * 2.399963
    const radius = 0.7 + (i % 7) * 0.43
    cloud.position.set(Math.sin(angle) * radius, 0.8 + (i % 3) * 0.38, Math.cos(angle) * radius)
    cloud.scale.set(0.6 + (i % 4) * 0.15, 0.16 + (i % 3) * 0.07, 1)
    clouds.add(cloud)
  }
  group.add(clouds)
  const rainPositions = new Float32Array(320 * 6)
  for (let i = 0; i < 320; i++) {
    const x = Math.sin(i * 12.9898) * 0.22, z = Math.cos(i * 7.233) * 0.22
    const y = ((i * 0.618033) % 1) * 0.24
    rainPositions.set([x, y, z, x, y - 0.006, z], i * 6)
  }
  const rainGeometry = new THREE.BufferGeometry()
  rainGeometry.setAttribute('position', new THREE.BufferAttribute(rainPositions, 3))
  const rainMaterial = new THREE.LineBasicMaterial({ color: '#abb7c2', transparent: true, opacity: 0, depthWrite: false })
  const rain = new THREE.LineSegments(rainGeometry, rainMaterial)
  rain.frustumCulled = false; group.add(rain)
  group.visible = false
  return {
    group, cloudMaterial, rainMaterial,
    update(weather: VisualWeather, delta: number, reduced: boolean, quality: string) {
      const hasCloud = weather.cloudCover > 0.005
      const hasRain = weather.precipitation > 0.01 && !reduced && quality !== 'low'
      group.visible = hasCloud || hasRain
      clouds.visible = hasCloud; rain.visible = hasRain
      cloudMaterial.opacity = weather.cloudCover * 0.55
      rainMaterial.opacity = Math.min(0.25, weather.precipitation * 0.045)
      if (!reduced && hasCloud) {
        for (const cloud of clouds.children) {
          // Meteorological bearing is where wind comes FROM; local Z points south.
          cloud.position.x -= Math.sin(weather.windDirection) * weather.windSpeed * delta * 0.001
          cloud.position.z += Math.cos(weather.windDirection) * weather.windSpeed * delta * 0.001
          if (cloud.position.x > 4) cloud.position.x -= 8
          if (cloud.position.x < -4) cloud.position.x += 8
          if (cloud.position.z > 4) cloud.position.z -= 8
          if (cloud.position.z < -4) cloud.position.z += 8
        }
      }
      if (hasRain) {
        for (let i = 0; i < rainPositions.length; i += 6) {
          rainPositions[i + 1] -= delta * 0.035
          if (rainPositions[i + 1] < 0) rainPositions[i + 1] += 0.24
          rainPositions[i + 4] = rainPositions[i + 1] - 0.006
        }
        rainGeometry.attributes.position.needsUpdate = true
      }
    },
  }
}

export function skyLighting(weather: VisualWeather) {
  const daylight = smoothstep(-0.13, 0.24, weather.sunAltitude)
  const sunset = (1 - smoothstep(0.03, 0.28, Math.abs(weather.sunAltitude))) * daylight
  const cosine = Math.cos(weather.sunAltitude)
  return { daylight, sunset, direction: new THREE.Vector3(Math.sin(weather.sunAzimuth) * cosine,
    Math.sin(weather.sunAltitude), -Math.cos(weather.sunAzimuth) * cosine) }
}
