# Offline map

The **Map** icon in the bottom bar opens a moving street map centred on the GPS
position: heading-up or north-up, seven zoom levels, the current street name, speed
and a scale bar. It needs no internet: the dash draws the streets itself from a
compact OpenStreetMap extract in `hardware/maps/`.

The bundled map covers Grand Junction, Colorado (39.00 to 39.15 N, 108.72 to 108.40 W:
Fruita's edge to Palisade's edge, Redlands and Orchard Mesa) at street level: 11,471
roads, rivers and railways in 0.8 MB. Parking rows and driveways are left out.

Add or refresh an area (south west north east), then commit the result:

```sh
python tools/make_map.py grand-junction 39.00 -108.72 39.15 -108.40 "Grand Junction, CO"
python tools/update_preview.py
```

The first map in `hardware/maps/index.json` is the one shown. Outside the covered
area the screen says so and shows only the position arrow.

Map data © OpenStreetMap contributors, available under the Open Database License
(ODbL): https://www.openstreetmap.org/copyright

# Reverse view from the dash cam

With `--dashcam` and no Pi camera (`--camera` absent), shifting into reverse
switches the dash cam to its rear camera and opens the view, mirrored like a
mirror; leaving reverse closes it and returns to the front camera. **Mirror rear
view** and **Open rear view in reverse** are in the Dashcam view. The rear camera
must be plugged into the dash cam, and reverse comes from the taillight
controller's reverse input on CAN. Live view takes a few seconds to start, so it
is slower than a wired camera.
