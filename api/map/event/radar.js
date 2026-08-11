function event_radar() {

  var radar_url = window.location.origin +
    '/api' + window.location.search;

  fetch(radar_url)
    .then(response => {
      if (!response.ok) {
        throw new Error('Network response was not ok');
      }
      return response.json();
    })
    .then(data => {

      // ---- Cooperative localised targets ---------------------------------
      // Age out detection and intersection markers from previous polls
      // (run unconditionally so orphaned markers don't persist when a
      //  previously-localised target drops below 3 radars this epoch)
      removeEntitiesOlderThanAndFade("detection", 10, 0.5);
      removeEntitiesOlderThanAndFade("intersection", 12, 0.5);

      if (data["detections_localised"]) {

        // Read truth data for flight/altitude lookup
        var truth = data["truth"] || {};

        // Track which hexes were seen this poll for label pruning
        var seenHex = {};

        for (const key in data["detections_localised"]) {
          if (data["detections_localised"].hasOwnProperty(key)) {
            var hex = key;
            var target = data["detections_localised"][key];
            var points = target["points"];

            // Determine altitude in METRES for colour coding:
            //   - truth alt_baro is from ADS-B (feet) → convert to metres
            //   - localised point altitude is geometric (already metres)
            var alt_m = null;
            var flight = null;
            if (truth[hex]) {
              if (truth[hex].alt_baro !== undefined && truth[hex].alt_baro !== null) {
                alt_m = truth[hex].alt_baro * 0.3048;
              }
              flight = truth[hex].flight || null;
            }
            if ((alt_m === null || alt_m === undefined) && points.length > 0) {
              alt_m = points[0][2];
            }
            if (alt_m === null || alt_m === undefined) {
              alt_m = 0;
            }

            var color = getAltitudeColor(alt_m);

            for (var i = 0; i < points.length; i++) {
              addPoint(
                points[i][0],
                points[i][1],
                points[i][2],
                hex,
                color,
                style_point.pointSize,
                style_point.type,
                Date.now()
              );
            }

            var namePart;
            if (flight && flight.trim() !== '') {
              namePart = sanitizeLabel(flight.trim());
            } else {
              namePart = hex.length > 4 ? hex.substring(hex.length - 4) : hex;
            }
            var labelText = namePart + '\n' + formatAltitude(alt_m);

            var latestPt = points[points.length - 1];
            updateTargetLabel("detection", hex, latestPt[0], latestPt[1], labelText, color);

            seenHex[hex] = true;
          }
        }

        // Remove labels for targets that are no longer localised
        for (var id in _targetLabelFeatures) {
          if (_targetLabelFeatures.hasOwnProperty(id) && id.indexOf('detection_') === 0) {
            var storedHex = id.substring(11);
            if (!seenHex[storedHex]) {
              removeTargetLabel("detection", storedHex);
            }
          }
        }

        // ---- Intersection markers: red ▼ for targets with ≥3 radars ----------
        if (data["detections_associated"]) {
          for (const hexKey in data["detections_localised"]) {
            if (!data["detections_localised"].hasOwnProperty(hexKey)) continue;
            var assoc = data["detections_associated"][hexKey];
            if (!assoc || !Array.isArray(assoc)) continue;
            // Count unique radars for this target
            var uniqueRadars = {};
            for (var ai = 0; ai < assoc.length; ai++) {
              uniqueRadars[assoc[ai].radar] = true;
            }
            if (Object.keys(uniqueRadars).length >= 3) {
              var locPts = data["detections_localised"][hexKey].points;
              if (locPts && locPts.length > 0) {
                var pt = locPts[locPts.length - 1];
                addPoint(
                  pt[0], pt[1], pt[2],
                  hexKey,
                  'rgba(255, 30, 30, 0.95)',
                  18,
                  "intersection",
                  Date.now()
                );
              }
            }
          }
        }
      }

      // ---- Non-cooperative (blah2-only) targets --------------------------
      if (data["detections_noncooperative"]) {
        removeEntitiesOlderThanAndFade("noncooperative", 10, 0.5);

        for (const key in data["detections_noncooperative"]) {
          if (data["detections_noncooperative"].hasOwnProperty(key)) {
            var ncoop = data["detections_noncooperative"][key];
            var pts = ncoop["points"];
            if (!pts || pts.length === 0) continue;

            var ncoopAlt = pts[0][2] || 0;
            var ncoopColor = 'rgba(255, 200, 0, 0.75)';

            for (var j = 0; j < pts.length; j++) {
              addPoint(
                pts[j][0],
                pts[j][1],
                pts[j][2],
                key,
                ncoopColor,
                style_point.pointSize,
                "noncooperative",
                Date.now(),
                3,
                '#ffffff'
              );
            }

            var labelText = 'Non-coop\n' + formatAltitude(ncoopAlt);
            var latestPt = pts[pts.length - 1];
            updateTargetLabel("noncoop", key, latestPt[0], latestPt[1], labelText, ncoopColor);
          }
        }
      }
    })
    .catch(error => {
      console.error('Error during fetch:', error);
    })
    .finally(() => {
      setTimeout(event_radar, 1000);
    });

}

var style_point = {};
style_point.pointSize = 16;
style_point.type = "detection";
style_point.timestamp = Date.now();