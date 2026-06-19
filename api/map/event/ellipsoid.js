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

      // Read whether cooperative localisation is enabled
      var localiseCoop = (typeof window.localiseCooperativeTargets !== 'undefined')
        ? window.localiseCooperativeTargets : true;

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
        } else {
          removeEntitiesByType("ellipsoids");
        }
        return;
      }

      // When ellipsoid data is present, age out old points instead of
      // instantly deleting them — allows persistent ellipsoid trails.
      if (fadeSec > 0) {
        removeEntitiesOlderThanAndFade("ellipsoids", fadeSec, 1.0);
      } else {
        removeEntitiesByType("ellipsoids");
      }
      for (const key in data["ellipsoids"]) {
        if (data["ellipsoids"].hasOwnProperty(key)) {

          // Filter: when cooperative localisation is disabled, only show
          // non-cooperative ellipsoids (keys prefixed with "nc_").
          var isNoncooperative = key.indexOf("nc_") === 0;
          if (!localiseCoop && !isNoncooperative) {
            continue;
          }

          var points = data["ellipsoids"][key];

          // Extract target hex from compound key "hex-radarName"
          // (strip "nc_" prefix if present for hashing)
          var targetHex = isNoncooperative ? key.substring(3).split('-')[0] : key.split('-')[0];

          // Per-target color: vary hue in the magenta/rose range (290°–330°)
          // so different targets' ellipsoids are visually distinct while staying
          // outside the altitude palette (orange 30° → purple 280°).
          var hue = hashToHue(targetHex, 290, 330);
          var color = 'hsla(' + hue + ', 85%, 55%, 0.45)';

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