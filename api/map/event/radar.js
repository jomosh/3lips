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

      // ---- ADS-B (cooperative) targets -----------------------------------
      if (data["detections_localised"]) {

        // Check whether ADS-B targets should be shown
        var showAdsb = (typeof window.showAdsbTargets !== 'undefined')
          ? window.showAdsbTargets : true;

        removeEntitiesOlderThanAndFade("detection", 10, 0.5);

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
                // ADS-B barometric altitude is in feet — convert to metres
                alt_m = truth[hex].alt_baro * 0.3048;
              }
              flight = truth[hex].flight || null;
            }
            // Fallback to geometric altitude from the first localised point (already metres)
            if ((alt_m === null || alt_m === undefined) && points.length > 0) {
              alt_m = points[0][2];
            }
            if (alt_m === null || alt_m === undefined) {
              alt_m = 0;
            }

            var color = getAltitudeColor(alt_m);

            if (showAdsb) {
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

              // Build label text: callsign on top line, formatted altitude on second line
              var namePart;
              if (flight && flight.trim() !== '') {
                namePart = sanitizeLabel(flight.trim());
              } else {
                // Use short hex (last 4 chars) for cleaner display
                namePart = hex.length > 4 ? hex.substring(hex.length - 4) : hex;
              }
              var labelText = namePart + '\n' + formatAltitude(alt_m);

              // Place label on the latest point (last in the array)
              var latestPt = points[points.length - 1];
              updateTargetLabel("detection", hex, latestPt[0], latestPt[1], labelText, color);
            }

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

        // If ADS-B targets are hidden, clear their on-screen points
        if (!showAdsb) {
          removeEntitiesByType("detection");
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

            // Altitude from geometric localisation (already metres)
            var ncoopAlt = pts[0][2] || 0;

            // Fixed yellow/gold colour — distinct from altitude palette
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
                Date.now()
              );
            }

            // Label: "blah2" instead of callsign
            var labelText = 'blah2\n' + formatAltitude(ncoopAlt);
            var latestPt = pts[pts.length - 1];
            updateTargetLabel("noncoop", key, latestPt[0], latestPt[1], labelText, ncoopColor);
          }
        }
      }
    })
    .catch(error => {
      // Handle errors during fetch
      console.error('Error during fetch:', error);
    })
    .finally(() => {
      // Schedule the next fetch after a delay (e.g., 1 second)
      setTimeout(event_radar, 1000);
    });

}

var style_point = {};
style_point.pointSize = 16;
style_point.type = "detection";
style_point.timestamp = Date.now();