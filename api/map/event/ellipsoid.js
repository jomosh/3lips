function event_ellipsoid() {

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

      if (!data["ellipsoids"]) {
        return;
      }

      // Client-side filtering: only show ellipsoids when the number of
      // unique radars with ellipsoid data meets or exceeds the user-configured
      // threshold (default 3, stored in window.minRadarEllipsoids).
      // Compound keys are "targetHex-radarName" — extract unique radar names.
      var uniqueRadars = {};
      Object.keys(data["ellipsoids"]).forEach(function(k) {
        var parts = k.split('-');
        var radarName = parts.slice(1).join('-'); // everything after first dash
        uniqueRadars[radarName] = true;
      });
      var ellipsoidCount = Object.keys(uniqueRadars).length;
      var threshold = (typeof window.minRadarEllipsoids !== 'undefined')
        ? window.minRadarEllipsoids : 3;
      // Read user-configured fade time (0 = immediate removal)
      var fadeSec = (typeof window.ellipsoidFadeTime !== 'undefined')
        ? window.ellipsoidFadeTime : 0;

      if (ellipsoidCount < threshold) {
        if (fadeSec > 0) {
          removeEntitiesOlderThanAndFade("ellipsoids", fadeSec, 1.0);
          removeEntitiesOlderThanAndFade("ellipsoids-noncoop", fadeSec, 1.0);
        } else {
          removeEntitiesByType("ellipsoids");
          removeEntitiesByType("ellipsoids-noncoop");
        }
        return;
      }

      // When ellipsoid data is present, age out old points instead of
      // instantly deleting them — allows persistent ellipsoid trails.
      if (fadeSec > 0) {
        removeEntitiesOlderThanAndFade("ellipsoids", fadeSec, 1.0);
        removeEntitiesOlderThanAndFade("ellipsoids-noncoop", fadeSec, 1.0);
      } else {
        removeEntitiesByType("ellipsoids");
        removeEntitiesByType("ellipsoids-noncoop");
      }
      // Build per-target radar count from ellipsoid keys.
      // Keys are "targetHex-radarName" or "nc_targetHex-radarName".
      var targetRadarCount = {};
      Object.keys(data["ellipsoids"]).forEach(function(k) {
        var noncoop = k.indexOf("nc_") === 0;
        var hex = noncoop ? k.substring(3).split('-')[0] : k.split('-')[0];
        targetRadarCount[hex] = (targetRadarCount[hex] || 0) + 1;
      });

      for (const key in data["ellipsoids"]) {
        if (data["ellipsoids"].hasOwnProperty(key)) {

          var isNoncooperative = key.indexOf("nc_") === 0;
          var points = data["ellipsoids"][key];

          // Extract target prefix from compound key "hex-radarName"
          // (strip "nc_" prefix if present)
          var targetHex = isNoncooperative ? key.substring(3).split('-')[0] : key.split('-')[0];

          // Per-target color by radar count:
          //   1 radar  → magenta/rose  (290°–330°) — detection-level ellipsoid
          //   2 radars → teal/cyan     (170°–200°) — pair association
          //   3+ radars → lime/green   (80°–120°)  — multi-radar fix
          var nRadars = targetRadarCount[targetHex] || 1;
          var hueMin, hueMax;
          if (nRadars >= 3) {
            hueMin = 80; hueMax = 120;
          } else if (nRadars >= 2) {
            hueMin = 170; hueMax = 200;
          } else {
            hueMin = 290; hueMax = 330;
          }
          var hue = hashToHue(targetHex, hueMin, hueMax);
          var color = 'hsla(' + hue + ', 85%, 55%, 0.45)';

          if (isNoncooperative) {
            // Non-cooperative ellipsoid points get a distinct type and
            // a subtle white border so they are visually distinguishable
            // from cooperative ellipsoid points.
            for (var i = 0; i < points.length; i++) {
              addPoint(
                points[i][0],
                points[i][1],
                points[i][2],
                "ellipsoids-noncoop",
                color,
                style_ellipsoid.pointSize,
                "ellipsoids-noncoop",
                Date.now(),
                1,
                'rgba(255,255,255,0.5)'
              );
            }
          } else {
            for (var i = 0; i < points.length; i++) {
              addPoint(
                points[i][0],
                points[i][1],
                points[i][2],
                "ellipsoids",
                color,
                style_ellipsoid.pointSize,
                style_ellipsoid.type,
                Date.now()
              );
            }
          }

        }
      }
    })
    .catch(error => {
      // Handle errors during fetch
      console.error('Error during fetch:', error);
    })
    .finally(() => {
      // Schedule the next fetch after a delay (e.g., 5 seconds)
      setTimeout(event_ellipsoid, 1000);
    });

}

/**
 * @brief Map a string to a hue in [minHue, maxHue] using a simple djb2 hash.
 * The same input always produces the same hue — stable across polling cycles.
 * @param {string} str - Input string (e.g. target ICAO hex).
 * @param {number} minHue - Minimum hue (0-360).
 * @param {number} maxHue - Maximum hue (0-360).
 * @returns {number} Hue value in [minHue, maxHue].
 */
function hashToHue(str, minHue, maxHue) {
  var hash = 5381;
  for (var i = 0; i < str.length; i++) {
    hash = ((hash << 5) + hash) + str.charCodeAt(i); // hash * 33 + c
    hash = hash & hash; // force 32-bit int
  }
  var range = maxHue - minHue;
  return minHue + (Math.abs(hash) % (range + 1));
}

var style_ellipsoid = {};
style_ellipsoid.pointSize = 16;
style_ellipsoid.type = "ellipsoids";
style_ellipsoid.timestamp = Date.now();