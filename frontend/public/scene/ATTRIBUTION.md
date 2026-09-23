# Scene assets

`earth-blue-marble.jpg`: NASA Visible Earth, “The Blue Marble: Land Surface,
Ocean Color and Sea Ice”, NASA Goddard Space Flight Center / Reto Stöckli.
Downloaded without modification from NASA's imagery archive:
https://eoimages.gsfc.nasa.gov/images/imagerecords/57000/57730/land_ocean_ice_2048.jpg

`earth-blue-marble-8k.webp` (8192 × 4096) and
`earth-blue-marble-4k.webp` (4096 × 2048) are optimized encodings of the
same NASA source, preserving its geographic projection/content. Full source:
https://eoimages.gsfc.nasa.gov/images/imagerecords/57000/57730/land_ocean_ice_8192.png

The 8K source PNG was encoded with `cwebp -q 92 -m 6 -mt`; the 4K tier uses
`cwebp -q 89 -m 6 -mt -resize 4096 2048`. The original is not duplicated in the
repository. The renderer progressively loads 2K first, then 4K or 8K according
to viewport, memory, WebGL capability, and quality. Replaced GPU maps are disposed.

NASA imagery is generally not subject to copyright in the United States. The
NASA credit is retained; no NASA logo or endorsement is used. Usage guidance:
https://www.nasa.gov/nasa-brand-center/images-and-media/

This is a static global surface composite, not current satellite imagery or a
weather/cloud observation. The application uses it only as geographic context.

The turbine, terrain, lighting, and atmosphere are original procedural scene
geometry/shaders. Turbine dimensions and terrain are illustrative, not surveyed
assets or operating telemetry. Registered coordinates come from the API.
Vegetation, sun rays, atmospheric drift and night fill are artistic scene elements.
Their motion responds to supplied wind speed; the current API supplies no wind
bearing, so drift direction is illustrative, never an observed direction.

Solar lighting is calculated from timestamp and coordinates with NOAA's general
solar equations: https://gml.noaa.gov/grad/solcalc/solareqns.PDF

Three.js and Motion are installed via npm; their MIT licenses are in their
installed packages. The scene does not depend on remote requests at runtime.
