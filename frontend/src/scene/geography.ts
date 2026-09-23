import { Matrix4, Quaternion, Vector3 } from 'three'
import type { Site } from '../types'

export const EARTH_RADIUS = 6371 // kilometres; local meshes use metres scaled by 0.001
export const DEG = Math.PI / 180

/** Matches the equirectangular NASA texture and Three's SphereGeometry UVs. */
export function earthPoint(latitude: number, longitude: number, radius = EARTH_RADIUS) {
  const lat = latitude * DEG, lon = longitude * DEG
  return new Vector3(Math.cos(lat) * Math.cos(lon), Math.sin(lat), -Math.cos(lat) * Math.sin(lon)).multiplyScalar(radius)
}

/** Right-handed local frame: east (X), up (Y), south (Z). */
export function surfaceFrame(site: Pick<Site, 'latitude' | 'longitude'>) {
  const lon = site.longitude * DEG
  const up = earthPoint(site.latitude, site.longitude, 1)
  const east = new Vector3(-Math.sin(lon), 0, -Math.cos(lon))
  const south = new Vector3().crossVectors(east, up).normalize()
  const quaternion = new Quaternion().setFromRotationMatrix(new Matrix4().makeBasis(east, up, south))
  return { up, east, south, quaternion, origin: up.clone().multiplyScalar(EARTH_RADIUS) }
}

/** Allocation-free great-circle interpolation. Output must be distinct from the endpoints. */
export function sphericalDirection(from: Vector3, to: Vector3, progress: number, output: Vector3) {
  const angle = Math.acos(Math.max(-1, Math.min(1, from.dot(to))))
  if (angle < 0.00001) return output.copy(from).lerp(to, progress).normalize()
  if (Math.PI - angle < 0.00001) {
    // The antipodal path is underdetermined. Choose a stable perpendicular arc.
    output.set(Math.abs(from.y) < 0.9 ? 0 : 1, Math.abs(from.y) < 0.9 ? 1 : 0, 0)
      .cross(from).normalize().multiplyScalar(Math.sin(Math.PI * progress))
      .addScaledVector(from, Math.cos(Math.PI * progress))
    return output.normalize()
  }
  const inverse = 1 / Math.sin(angle)
  return output.copy(from).multiplyScalar(Math.sin((1 - progress) * angle) * inverse)
    .addScaledVector(to, Math.sin(progress * angle) * inverse).normalize()
}

/** Exact critically damped spring, preserving velocity when a target is reversed. */
export class ScalarSpring {
  velocity = 0
  constructor(public value: number, public target = value, public frequency = 5) {}
  step(delta: number) {
    const error = this.value - this.target
    const term = this.velocity + this.frequency * error
    const decay = Math.exp(-this.frequency * delta)
    this.value = this.target + (error + term * delta) * decay
    this.velocity = (this.velocity - this.frequency * term * delta) * decay
    return this.value
  }
}
