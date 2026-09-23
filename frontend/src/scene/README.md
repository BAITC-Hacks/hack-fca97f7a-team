# Spatial world

`WorldScene.tsx` is the React boundary. It accepts registered `Site` objects,
an optional normalized weather sample, the desired `earth` / `turbine` view,
quality, and reduced-motion preferences. It neither calls weather providers nor
calculates numerical power. React changes targets; the Three.js loop owns motion.
Marker positions and connector lines update through DOM refs, not React state.

`renderer.ts` keeps one geocentric scene in kilometres. `geography.ts` uses a
right-handed east/up/south local tangent frame at the real API coordinates. The
camera follows an altitude curve controlled by a critically damped spring;
changing `view` reverses the same spring with its current position and velocity.
Nearby site changes have independent latitude/longitude springs. Local geometry
is constructed only on first entry and replaces the coarse global surface at
close range. It is original illustrative geometry, not a geographic survey.

On first load, a restrained settling zoom and 0.69°/second orbit introduce the
globe. The first pointer-down or key press anywhere, zoom, or turbine selection
stops this ambient motion immediately and permanently for that mount. It is
disabled under reduced motion. Pointer capture gives direct drag and release velocity. Wheel/pinch and zoom
buttons change bounded zoom targets. Arrow keys rotate, +/− zoom, and Escape
calls the optional `onViewChange('earth')`. Close markers fan their labels while
connector lines preserve the actual coordinate anchors. The application's site
list remains the alternative selection interface.

`experience/weather.ts` is the provider-independent adapter/interpolator. Only
wind and temperature currently arrive over HTTP. Cloud cover, rainfall, humidity,
visibility, wind direction and rotor telemetry remain null; there are no synthetic
transitions for them. Clouds/rain are implemented but dormant until real normalized
fields are supplied. Wind direction, if supplied, is the meteorological FROM
bearing. The sky/sun lighting is a NOAA astronomical calculation, not a measured
cloud or visibility observation. Missing weather displays a neutral illustration
with a stopped rotor. The rotor's smooth capped response is an illustration, not
an operating RPM estimate; supplied RPM takes precedence.

Quality bounds DPR (1 / 1.25 / 2), shadows (off / 512 / 1024), precipitation,
and drops quality after a sustained slow frame window in Auto. No postprocessing
or volumetric raymarching is used. Vegetation is one instanced draw (14,000 tufts,
6,500 in Medium, omitted in Low). Its shader sways with supplied wind speed; only
72 particles and five understated wind traces are used. Their direction is
illustrative when the API does not supply a bearing. Sun rays are lightweight
shader scattering aligned to the calculated sun, not a cloud observation.
A hidden tab suspends frames. Reduced motion
uses an immediate spatial change and disables rotor, cloud and particle movement.
Geometry/materials/textures, pointer listeners, observers, and animation frames
are disposed on unmount; context loss switches to an explicit 2D fallback while
the rest of the application stays usable.

The 2K NASA Earth texture is loaded first, then a 4K or 8K
local WebP is loaded progressively. Desktop high/auto uses 8K only with
an adequate texture limit, >4 logical CPUs, and at least 8 GB reported memory
(or an unreported desktop memory capability); mobile/memory-limited use 4K and
Low uses 2K. Replaced maps are disposed, limiting resident texture memory to one
map (~171 MiB / 43 MiB / 11 MiB including mipmaps). See
`frontend/public/scene/ATTRIBUTION.md` for exact source and encoding/license.

Verification: `npm --prefix frontend run test:scene` checks data nullability,
astronomical noon/night, nonlinear bounded rotor response and inertia, circular
angle interpolation, geographic frame/separation, and continuous spring reversal.
Browser verification is still necessary for appearance, framing and gestures.
